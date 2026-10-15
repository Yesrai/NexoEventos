import { useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { addStadiumEnvironment } from './venue3d-stadium-env'
import { zoneColors } from './venue3d-types'

export type StadiumSeat = {
  id: number
  zone_id: number
  zone_name: string
  row: string
  number: number
  price: number
  available: boolean
}

type Stadium3DProps = {
  seats: StadiumSeat[]
  selectedSeatIds: number[]
  onToggle: (seat: StadiumSeat) => void
  onSectorChange: (zoneId: number | null) => void
  onUnavailable: () => void
}

type CameraApi = {
  focusSector: (zoneId: number) => void
  reset: () => void
  zoom: (factor: number) => void
}

type SeatInfo = Pick<StadiumSeat, 'zone_name' | 'row' | 'number' | 'price' | 'available'>

const COLORS = {
  available: new THREE.Color('#17384a'),
  occupied: new THREE.Color('#aebbc1'),
  selected: new THREE.Color('#00c2a5'),
}

const GENERAL_CAMERA = new THREE.Vector3(27, 20, 31)
const GENERAL_TARGET = new THREE.Vector3(0, 1.1, 0)

function normalizedSector(name: string) {
  if (name.includes('Norte')) return 'north'
  if (name.includes('Sur')) return 'south'
  if (name.includes('Oriente')) return 'east'
  return 'west'
}

function createGrassTexture() {
  const canvas = document.createElement('canvas')
  canvas.width = 128
  canvas.height = 128
  const context = canvas.getContext('2d')
  if (!context) return null
  context.fillStyle = '#568765'
  context.fillRect(0, 0, 128, 128)
  for (let index = 0; index < 8; index += 1) {
    context.fillStyle = index % 2 === 0 ? '#5f906c' : '#527f60'
    context.fillRect(index * 16, 0, 16, 128)
  }
  context.globalAlpha = .16
  context.strokeStyle = '#d7eadc'
  for (let offset = 4; offset < 128; offset += 12) {
    context.beginPath()
    context.moveTo(0, offset)
    context.lineTo(128, offset + 3)
    context.stroke()
  }
  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  texture.wrapS = THREE.RepeatWrapping
  texture.wrapT = THREE.RepeatWrapping
  texture.repeat.set(4, 3)
  return texture
}

function fieldLine(width: number, depth: number, x: number, z: number) {
  const line = new THREE.Mesh(
    new THREE.BoxGeometry(width, .025, depth),
    new THREE.MeshBasicMaterial({ color: '#eef7f0' }),
  )
  line.position.set(x, .075, z)
  return line
}

function seatTransform(seat: StadiumSeat, rowIndex: number, rowCount: number) {
  const side = normalizedSector(seat.zone_name)
  const rowSeats = 12
  const aisleOffset = seat.number > rowSeats / 2 ? .72 : -.72
  const along = (seat.number - (rowSeats + 1) / 2) * 1.12 + aisleOffset
  const height = .72 + rowIndex * .78
  const distance = 11.2 + rowIndex * 1.48
  const position = new THREE.Vector3()
  let rotation = 0
  if (side === 'north') position.set(along, height, -distance)
  if (side === 'south') { position.set(-along, height, distance); rotation = Math.PI }
  if (side === 'east') { position.set(distance + 4.7, height, along); rotation = -Math.PI / 2 }
  if (side === 'west') { position.set(-distance - 4.7, height, -along); rotation = Math.PI / 2 }
  return { position, rotation, rowCount }
}

function sectorCamera(name: string) {
  const side = normalizedSector(name)
  if (side === 'north') return { position: new THREE.Vector3(0, 8.4, -3.5), target: new THREE.Vector3(0, 1.7, -12.4) }
  if (side === 'south') return { position: new THREE.Vector3(0, 8.4, 3.5), target: new THREE.Vector3(0, 1.7, 12.4) }
  if (side === 'east') return { position: new THREE.Vector3(8, 8.4, 0), target: new THREE.Vector3(17.2, 1.7, 0) }
  return { position: new THREE.Vector3(-8, 8.4, 0), target: new THREE.Vector3(-17.2, 1.7, 0) }
}

export default function Stadium3D({ seats, selectedSeatIds, onToggle, onSectorChange, onUnavailable }: Stadium3DProps) {
  const hostRef = useRef<HTMLDivElement | null>(null)
  const apiRef = useRef<CameraApi | null>(null)
  const selectedRef = useRef(selectedSeatIds)
  const toggleRef = useRef(onToggle)
  const sectorChangeRef = useRef(onSectorChange)
  const unavailableRef = useRef(onUnavailable)
  const activeZoneRef = useRef<number | null>(null)
  const seatMeshesRef = useRef<THREE.InstancedMesh[]>([])
  const renderRef = useRef<(() => void) | null>(null)
  const [activeZoneId, setActiveZoneId] = useState<number | null>(null)
  const [seatInfo, setSeatInfo] = useState<SeatInfo | null>(null)
  const [ready, setReady] = useState(false)

  const zoneTint = useMemo(() => new Map([...zoneColors(seats.map((seat) => ({ id: seat.zone_id, price: seat.price })))].map(([id, hex]) => [id, new THREE.Color(hex)])), [seats])
  const sectors = [...new Map(seats.map((seat) => [seat.zone_id, { id: seat.zone_id, name: seat.zone_name }])).values()]
  const activeSector = sectors.find((sector) => sector.id === activeZoneId) ?? null

  useEffect(() => { selectedRef.current = selectedSeatIds }, [selectedSeatIds])
  useEffect(() => { toggleRef.current = onToggle }, [onToggle])
  useEffect(() => { sectorChangeRef.current = onSectorChange }, [onSectorChange])
  useEffect(() => { unavailableRef.current = onUnavailable }, [onUnavailable])

  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    let renderer: THREE.WebGLRenderer
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: 'high-performance' })
    } catch {
      unavailableRef.current()
      return
    }

    const mobile = window.matchMedia('(max-width: 600px)').matches
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, mobile ? 1.25 : 1.75))
    renderer.setSize(host.clientWidth, host.clientHeight, false)
    renderer.setClearColor('#dce8ec')
    renderer.outputColorSpace = THREE.SRGBColorSpace
    renderer.shadowMap.enabled = !mobile
    renderer.shadowMap.type = THREE.PCFShadowMap
    renderer.domElement.className = 'stadium-3d-canvas'
    renderer.domElement.setAttribute('aria-label', 'Visor tridimensional del Estadio Nexo')
    renderer.domElement.setAttribute('role', 'img')
    host.appendChild(renderer.domElement)

    const scene = new THREE.Scene()
    scene.background = new THREE.Color('#dce8ec')
    scene.fog = new THREE.Fog('#dbe8ee', 95, 230)
    const camera = new THREE.PerspectiveCamera(39, host.clientWidth / host.clientHeight, .1, 500)
    camera.position.copy(GENERAL_CAMERA)
    const controls = new OrbitControls(camera, renderer.domElement)
    controls.target.copy(GENERAL_TARGET)
    controls.enableDamping = false
    controls.enablePan = false
    controls.minDistance = 13
    controls.maxDistance = 62
    controls.minPolarAngle = .34
    controls.maxPolarAngle = Math.PI / 2.18
    controls.minAzimuthAngle = -Math.PI * .82
    controls.maxAzimuthAngle = Math.PI * .82

    scene.add(new THREE.HemisphereLight('#f8fbfc', '#65776d', 1.7))
    const sun = new THREE.DirectionalLight('#ffffff', 2.8)
    sun.position.set(15, 28, 18)
    sun.castShadow = !mobile
    sun.shadow.mapSize.set(mobile ? 512 : 1024, mobile ? 512 : 1024)
    sun.shadow.camera.left = -32
    sun.shadow.camera.right = 32
    sun.shadow.camera.top = 28
    sun.shadow.camera.bottom = -28
    scene.add(sun)

    addStadiumEnvironment(scene, mobile)

    const base = new THREE.Mesh(new THREE.CylinderGeometry(28, 29, 1.15, 64), new THREE.MeshStandardMaterial({ color: '#7f8a8f', roughness: .92 }))
    base.position.y = -.62
    base.receiveShadow = true
    scene.add(base)

    const concourse = new THREE.Mesh(new THREE.RingGeometry(22, 31, 72), new THREE.MeshStandardMaterial({ color: '#889398', roughness: .98, side: THREE.DoubleSide }))
    concourse.rotation.x = -Math.PI / 2
    concourse.position.y = -.03
    concourse.receiveShadow = true
    scene.add(concourse)
    const perimeter = new THREE.Mesh(new THREE.TorusGeometry(29, .13, 8, 96), new THREE.MeshStandardMaterial({ color: '#67777e', roughness: .55, metalness: .35 }))
    perimeter.rotation.x = Math.PI / 2
    perimeter.position.y = .18
    scene.add(perimeter)
    const grassTexture = createGrassTexture()
    const field = new THREE.Mesh(new THREE.PlaneGeometry(28, 17), new THREE.MeshStandardMaterial({ color: '#568765', map: grassTexture, roughness: .96 }))
    field.rotation.x = -Math.PI / 2
    field.position.y = .045
    field.receiveShadow = true
    scene.add(field)
    scene.add(fieldLine(28, .09, 0, -8.5), fieldLine(28, .09, 0, 8.5), fieldLine(.09, 17, -14, 0), fieldLine(.09, 17, 14, 0), fieldLine(.08, 17, 0, 0))
    const circlePoints = Array.from({ length: 65 }, (_, index) => {
      const angle = index / 64 * Math.PI * 2
      return new THREE.Vector3(Math.cos(angle) * 2.45, .082, Math.sin(angle) * 2.45)
    })
    scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(circlePoints), new THREE.LineBasicMaterial({ color: '#eef7f0' })))
    for (const side of [-1, 1]) {
      const x = side * 11.7
      scene.add(fieldLine(4.6, .08, x, -4.4), fieldLine(4.6, .08, x, 4.4), fieldLine(.08, 8.8, side * 9.4, 0))
      const goal = new THREE.Group()
      const postMaterial = new THREE.MeshStandardMaterial({ color: '#f7faf8', roughness: .6 })
      for (const z of [-2.2, 2.2]) {
        const post = new THREE.Mesh(new THREE.CylinderGeometry(.07, .07, 1.7, 8), postMaterial)
        post.position.set(side * 14.2, .85, z)
        goal.add(post)
      }
      const crossbar = new THREE.Mesh(new THREE.CylinderGeometry(.07, .07, 4.4, 8), postMaterial)
      crossbar.rotation.x = Math.PI / 2
      crossbar.position.set(side * 14.2, 1.68, 0)
      goal.add(crossbar)
      scene.add(goal)
    }

    const rowNamesByZone = new Map<number, string[]>()
    for (const sector of sectors) rowNamesByZone.set(sector.id, [...new Set(seats.filter((seat) => seat.zone_id === sector.id).map((seat) => seat.row))])
    const platformMaterial = new THREE.MeshStandardMaterial({ color: '#b9c5ca', roughness: .88, metalness: .02 })
    const aisleMaterial = new THREE.MeshStandardMaterial({ color: '#e8edef', roughness: .9 })
    const structureMaterial = new THREE.MeshStandardMaterial({ color: '#718087', roughness: .78, metalness: .12 })
    const railMaterial = new THREE.MeshStandardMaterial({ color: '#415661', roughness: .45, metalness: .55 })
    const roofMaterial = new THREE.MeshStandardMaterial({ color: '#64747c', roughness: .6, metalness: .35, side: THREE.DoubleSide })
    const sectorObjects = new Map<string, number>()

    for (const sector of sectors) {
      const side = normalizedSector(sector.name)
      const rows = rowNamesByZone.get(sector.id) ?? []
      rows.forEach((_, rowIndex) => {
        const height = .55 + rowIndex * .78
        const distance = 11.2 + rowIndex * 1.48
        const horizontal = side === 'north' || side === 'south'
        const platform = new THREE.Mesh(new THREE.BoxGeometry(horizontal ? 17.8 : 1.38, height, horizontal ? 1.38 : 17.8), platformMaterial)
        if (side === 'north') platform.position.set(0, height / 2 - .04, -distance)
        if (side === 'south') platform.position.set(0, height / 2 - .04, distance)
        if (side === 'east') platform.position.set(distance + 4.7, height / 2 - .04, 0)
        if (side === 'west') platform.position.set(-distance - 4.7, height / 2 - .04, 0)
        platform.receiveShadow = true
        platform.userData.zoneId = sector.id
        scene.add(platform)
        sectorObjects.set(platform.uuid, sector.id)

        const aisle = new THREE.Mesh(new THREE.BoxGeometry(horizontal ? 1.05 : 1.4, .045, horizontal ? 1.4 : 1.05), aisleMaterial)
        if (horizontal) aisle.scale.x = 1.25
        else aisle.scale.z = 1.25
        aisle.position.copy(platform.position)
        aisle.position.y = height + .03
        scene.add(aisle)
      })

      const horizontal = side === 'north' || side === 'south'
      const lastDistance = 11.2 + Math.max(0, rows.length - 1) * 1.48
      const outerDistance = lastDistance + 1.1
      const support = new THREE.Mesh(new THREE.BoxGeometry(horizontal ? 19 : 1.1, 3.35, horizontal ? 1.1 : 19), structureMaterial)
      if (side === 'north') support.position.set(0, 1.05, -outerDistance)
      if (side === 'south') support.position.set(0, 1.05, outerDistance)
      if (side === 'east') support.position.set(outerDistance + 4.7, 1.05, 0)
      if (side === 'west') support.position.set(-outerDistance - 4.7, 1.05, 0)
      support.castShadow = !mobile
      support.receiveShadow = true
      support.userData.zoneId = sector.id
      scene.add(support)
      sectorObjects.set(support.uuid, sector.id)

      const portal = new THREE.Mesh(new THREE.BoxGeometry(horizontal ? 2.3 : 1.14, 2.05, horizontal ? 1.14 : 2.3), new THREE.MeshStandardMaterial({ color: '#263840', roughness: .94 }))
      portal.position.copy(support.position)
      portal.position.y = .63
      scene.add(portal)

      const frontDistance = 10.35
      const rail = new THREE.Mesh(new THREE.BoxGeometry(horizontal ? 18.4 : .09, .09, horizontal ? .09 : 18.4), railMaterial)
      if (side === 'north') rail.position.set(0, 1.18, -frontDistance)
      if (side === 'south') rail.position.set(0, 1.18, frontDistance)
      if (side === 'east') rail.position.set(frontDistance + 4.7, 1.18, 0)
      if (side === 'west') rail.position.set(-frontDistance - 4.7, 1.18, 0)
      scene.add(rail)
      for (let postIndex = -4; postIndex <= 4; postIndex += 1) {
        const post = new THREE.Mesh(new THREE.CylinderGeometry(.035, .035, 1.05, 6), railMaterial)
        if (horizontal) post.position.set(postIndex * 2.1, .68, side === 'north' ? -frontDistance : frontDistance)
        else post.position.set(side === 'east' ? frontDistance + 4.7 : -frontDistance - 4.7, .68, postIndex * 2.1)
        scene.add(post)
      }

      if (side === 'east' || side === 'west') {
        const roof = new THREE.Mesh(new THREE.BoxGeometry(5.4, .22, 20.5), roofMaterial)
        roof.position.set(side === 'east' ? 19.5 : -19.5, 6.1, 0)
        roof.rotation.z = side === 'east' ? -.11 : .11
        roof.castShadow = !mobile
        scene.add(roof)
        for (const z of [-8.8, 8.8]) {
          const column = new THREE.Mesh(new THREE.CylinderGeometry(.1, .13, 5.9, 8), railMaterial)
          column.position.set(side === 'east' ? 21.2 : -21.2, 2.85, z)
          scene.add(column)
        }
      }
    }

    const towerMaterial = new THREE.MeshStandardMaterial({ color: '#45565e', roughness: .48, metalness: .62 })
    const lampMaterial = new THREE.MeshStandardMaterial({ color: '#f3f6e5', emissive: '#eef6cb', emissiveIntensity: .7, roughness: .35 })
    for (const [x, z] of [[-25, -22], [25, -22], [-25, 22], [25, 22]] as const) {
      const pole = new THREE.Mesh(new THREE.CylinderGeometry(.13, .2, 13, 10), towerMaterial)
      pole.position.set(x, 5.3, z)
      pole.castShadow = !mobile
      scene.add(pole)
      const lamps = new THREE.Mesh(new THREE.BoxGeometry(1.5, .6, .2), lampMaterial)
      lamps.position.set(x, 11.7, z)
      lamps.lookAt(0, 0, 0)
      scene.add(lamps)
    }

    const seatBaseGeometry = new THREE.BoxGeometry(.68, .18, .62)
    const seatBackGeometry = new THREE.BoxGeometry(.68, .68, .14)
    const seatMaterial = new THREE.MeshStandardMaterial({ color: '#ffffff', roughness: .62, metalness: .04, vertexColors: true })
    const seatBases = new THREE.InstancedMesh(seatBaseGeometry, seatMaterial, seats.length)
    const seatBacks = new THREE.InstancedMesh(seatBackGeometry, seatMaterial.clone(), seats.length)
    seatBases.castShadow = !mobile
    seatBacks.castShadow = !mobile
    seatBases.userData.isSeats = true
    seatBacks.userData.isSeats = true
    const matrix = new THREE.Matrix4()
    const quaternion = new THREE.Quaternion()
    const scale = new THREE.Vector3(1, 1, 1)
    seats.forEach((seat, index) => {
      const rows = rowNamesByZone.get(seat.zone_id) ?? []
      const rowIndex = Math.max(0, rows.indexOf(seat.row))
      const transform = seatTransform(seat, rowIndex, rows.length)
      quaternion.setFromAxisAngle(new THREE.Vector3(0, 1, 0), transform.rotation)
      matrix.compose(transform.position, quaternion, scale)
      seatBases.setMatrixAt(index, matrix)
      const backOffset = new THREE.Vector3(0, .36, -.26).applyQuaternion(quaternion)
      matrix.compose(transform.position.clone().add(backOffset), quaternion, scale)
      seatBacks.setMatrixAt(index, matrix)
    })
    seatBases.instanceMatrix.needsUpdate = true
    seatBacks.instanceMatrix.needsUpdate = true
    scene.add(seatBases, seatBacks)
    seatMeshesRef.current = [seatBases, seatBacks]

    const updateSeatColors = () => {
      seats.forEach((seat, index) => {
        const color = selectedRef.current.includes(seat.id) ? COLORS.selected : seat.available ? zoneTint.get(seat.zone_id) ?? COLORS.available : COLORS.occupied
        seatBases.setColorAt(index, color)
        seatBacks.setColorAt(index, color)
      })
      if (seatBases.instanceColor) seatBases.instanceColor.needsUpdate = true
      if (seatBacks.instanceColor) seatBacks.instanceColor.needsUpdate = true
    }
    updateSeatColors()

    const render = () => renderer.render(scene, camera)
    renderRef.current = render
    controls.addEventListener('change', render)
    render()
    setReady(true)

    let animationFrame = 0
    const moveCamera = (destination: THREE.Vector3, destinationTarget: THREE.Vector3) => {
      cancelAnimationFrame(animationFrame)
      const startPosition = camera.position.clone()
      const startTarget = controls.target.clone()
      const started = performance.now()
      const duration = reducedMotion ? 0 : 620
      const step = (now: number) => {
        const raw = duration === 0 ? 1 : Math.min(1, (now - started) / duration)
        const progress = 1 - Math.pow(1 - raw, 3)
        camera.position.lerpVectors(startPosition, destination, progress)
        controls.target.lerpVectors(startTarget, destinationTarget, progress)
        controls.update()
        render()
        if (raw < 1) animationFrame = requestAnimationFrame(step)
      }
      animationFrame = requestAnimationFrame(step)
    }
    const focusSector = (zoneId: number) => {
      const sector = sectors.find((item) => item.id === zoneId)
      if (!sector) return
      setActiveZoneId(zoneId)
      activeZoneRef.current = zoneId
      sectorChangeRef.current(zoneId)
      const focus = sectorCamera(sector.name)
      moveCamera(focus.position, focus.target)
    }
    const reset = () => {
      setActiveZoneId(null)
      activeZoneRef.current = null
      setSeatInfo(null)
      sectorChangeRef.current(null)
      moveCamera(GENERAL_CAMERA, GENERAL_TARGET)
    }
    const zoom = (factor: number) => {
      const offset = camera.position.clone().sub(controls.target).multiplyScalar(factor)
      const distance = Math.max(controls.minDistance, Math.min(controls.maxDistance, offset.length()))
      camera.position.copy(controls.target).add(offset.setLength(distance))
      controls.update()
      render()
    }
    apiRef.current = { focusSector, reset, zoom }

    const raycaster = new THREE.Raycaster()
    const pointer = new THREE.Vector2()
    const updatePointer = (event: PointerEvent) => {
      const rect = renderer.domElement.getBoundingClientRect()
      pointer.set((event.clientX - rect.left) / rect.width * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1)
      raycaster.setFromCamera(pointer, camera)
    }
    const seatAtPointer = () => {
      const hit = raycaster.intersectObjects([seatBases, seatBacks], false)[0]
      return hit?.instanceId === undefined ? null : seats[hit.instanceId]
    }
    const onPointerMove = (event: PointerEvent) => {
      updatePointer(event)
      const seat = seatAtPointer()
      renderer.domElement.style.cursor = seat ? seat.available ? 'pointer' : 'not-allowed' : 'grab'
      setSeatInfo(seat ? { zone_name: seat.zone_name, row: seat.row, number: seat.number, price: seat.price, available: seat.available } : null)
    }
    const onPointerDown = (event: PointerEvent) => {
      updatePointer(event)
      const seat = seatAtPointer()
      if (seat) {
        setSeatInfo({ zone_name: seat.zone_name, row: seat.row, number: seat.number, price: seat.price, available: seat.available })
        if (activeZoneRef.current === seat.zone_id && seat.available) toggleRef.current(seat)
        else focusSector(seat.zone_id)
        return
      }
      const sectorHit = raycaster.intersectObjects(scene.children.filter((child) => sectorObjects.has(child.uuid)), false)[0]
      const zoneId = sectorHit ? sectorObjects.get(sectorHit.object.uuid) : undefined
      if (zoneId !== undefined) focusSector(zoneId)
    }
    renderer.domElement.addEventListener('pointermove', onPointerMove)
    renderer.domElement.addEventListener('pointerdown', onPointerDown)
    const onContextLost = (event: Event) => { event.preventDefault(); unavailableRef.current() }
    renderer.domElement.addEventListener('webglcontextlost', onContextLost)

    const observer = new ResizeObserver(() => {
      if (!host.clientWidth || !host.clientHeight) return
      camera.aspect = host.clientWidth / host.clientHeight
      camera.updateProjectionMatrix()
      renderer.setSize(host.clientWidth, host.clientHeight, false)
      render()
    })
    observer.observe(host)

    return () => {
      cancelAnimationFrame(animationFrame)
      observer.disconnect()
      controls.removeEventListener('change', render)
      controls.dispose()
      renderer.domElement.removeEventListener('pointermove', onPointerMove)
      renderer.domElement.removeEventListener('pointerdown', onPointerDown)
      renderer.domElement.removeEventListener('webglcontextlost', onContextLost)
      scene.traverse((object) => {
        if (object instanceof THREE.Mesh || object instanceof THREE.Line) {
          object.geometry.dispose()
          const materials = Array.isArray(object.material) ? object.material : [object.material]
          materials.forEach((material) => { (material as THREE.MeshStandardMaterial).map?.dispose(); material.dispose() })
        }
      })
      grassTexture?.dispose()
      renderer.dispose()
      renderer.domElement.remove()
      seatMeshesRef.current = []
      renderRef.current = null
      apiRef.current = null
    }
  }, [seats])

  useEffect(() => {
    const meshes = seatMeshesRef.current
    if (meshes.length !== 2) return
    seats.forEach((seat, index) => {
      const color = selectedSeatIds.includes(seat.id) ? COLORS.selected : seat.available ? zoneTint.get(seat.zone_id) ?? COLORS.available : COLORS.occupied
      meshes[0].setColorAt(index, color)
      meshes[1].setColorAt(index, color)
    })
    meshes.forEach((mesh) => { if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true })
    renderRef.current?.()
  }, [seats, selectedSeatIds])

  return <div className="stadium-3d-shell">
    <div className="stadium-3d-stage">
      <div className="stadium-3d-toolbar" role="group" aria-label="Controles de cámara 3D">
        {activeSector && <button type="button" onClick={() => apiRef.current?.reset()}>Volver al estadio</button>}
        <button type="button" aria-label="Acercar cámara" onClick={() => apiRef.current?.zoom(.82)}>+</button>
        <button type="button" aria-label="Alejar cámara" onClick={() => apiRef.current?.zoom(1.2)}>−</button>
        <button type="button" onClick={() => apiRef.current?.reset()}>Restablecer</button>
      </div>
      <div ref={hostRef} className="stadium-3d-host" aria-busy={!ready} />
      {!ready && <div className="stadium-3d-loading" role="status"><span className="spinner" />Preparando estadio 3D…</div>}
      {seatInfo && <div className="stadium-3d-tooltip" role="status"><strong>{seatInfo.zone_name}</strong><span>Fila {seatInfo.row} · Asiento {seatInfo.number}</span><b>S/ {seatInfo.price.toFixed(2)} · {seatInfo.available ? 'Disponible' : 'Ocupado'}</b></div>}
    </div>
    <div className="stadium-3d-sector-list" role="group" aria-label="Seleccionar tribuna en el visor 3D">
      {sectors.map((sector) => {
        const available = seats.filter((seat) => seat.zone_id === sector.id && seat.available).length
        return <button type="button" key={sector.id} className={activeZoneId === sector.id ? 'active' : ''} aria-pressed={activeZoneId === sector.id} onClick={() => apiRef.current?.focusSector(sector.id)}><strong>{sector.name.replace('Tribuna ', '')}</strong><span>{available} disponibles</span></button>
      })}
    </div>
  </div>
}
