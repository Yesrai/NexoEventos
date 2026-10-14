import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'

export type VenueSeat = { id: number; zone_id: number; zone_name: string; row: string; number: number; price: number; available: boolean }
export type VenueZone = { id: number; name: string; price: number; capacity: number; available_capacity: number }

type Props = {
  kind: 'theatre' | 'concert' | 'museum'
  seats?: VenueSeat[]
  selectedSeatIds?: number[]
  onToggleSeat?: (seat: VenueSeat) => void
  zones?: VenueZone[]
  selectedZoneId?: number | null
  onSelectZone?: (id: number) => void
  onUnavailable: () => void
}

type Interactive = { object: THREE.Object3D; type: 'seat' | 'zone'; index: number }

const palette = {
  ink: new THREE.Color('#17384a'),
  turquoise: new THREE.Color('#00c2a5'),
  occupied: new THREE.Color('#aebbc1'),
  concrete: '#b8c1c4',
  metal: '#3e5059',
}

function addBox(parent: THREE.Object3D, size: [number, number, number], position: [number, number, number], color: THREE.ColorRepresentation, options: { metalness?: number; roughness?: number; cast?: boolean } = {}) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), new THREE.MeshStandardMaterial({ color, roughness: options.roughness ?? .82, metalness: options.metalness ?? .03 }))
  mesh.position.set(...position)
  mesh.castShadow = Boolean(options.cast)
  mesh.receiveShadow = true
  parent.add(mesh)
  return mesh
}

function addCylinder(parent: THREE.Object3D, radius: number, height: number, position: [number, number, number], color: THREE.ColorRepresentation) {
  const mesh = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, height, 14), new THREE.MeshStandardMaterial({ color, roughness: .62, metalness: .16 }))
  mesh.position.set(...position)
  mesh.castShadow = true
  parent.add(mesh)
  return mesh
}

function screenTexture() {
  const canvas = document.createElement('canvas')
  canvas.width = 512
  canvas.height = 256
  const context = canvas.getContext('2d')
  if (!context) return null
  context.fillStyle = '#102d3d'
  context.fillRect(0, 0, 512, 256)
  context.fillStyle = '#00c2a5'
  context.fillRect(44, 36, 8, 184)
  context.fillStyle = '#f7fbfc'
  context.font = '600 58px Arial'
  context.fillText('NEXO', 82, 116)
  context.font = '400 30px Arial'
  context.fillText('ESCENA DEMO', 82, 166)
  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  return texture
}

function labelFor(kind: Props['kind']) {
  if (kind === 'theatre') return 'Visor tridimensional del Auditorio Nexo'
  if (kind === 'concert') return 'Visor tridimensional de Arena Parque Sur'
  return 'Recorrido tridimensional orientativo del museo'
}

export default function Venue3D({ kind, seats = [], selectedSeatIds = [], onToggleSeat, zones = [], selectedZoneId = null, onSelectZone, onUnavailable }: Props) {
  const hostRef = useRef<HTMLDivElement | null>(null)
  const selectedSeatsRef = useRef(selectedSeatIds)
  const selectedZoneRef = useRef(selectedZoneId)
  const toggleSeatRef = useRef(onToggleSeat)
  const selectZoneRef = useRef(onSelectZone)
  const unavailableRef = useRef(onUnavailable)
  const renderRef = useRef<(() => void) | null>(null)
  const seatMeshesRef = useRef<THREE.InstancedMesh[]>([])
  const zoneMeshesRef = useRef<Array<{ mesh: THREE.Mesh; zone: VenueZone }>>([])
  const cameraApi = useRef<{ reset: () => void; zoom: (factor: number) => void } | null>(null)
  const [ready, setReady] = useState(false)
  const [hover, setHover] = useState<string | null>(null)

  useEffect(() => { selectedSeatsRef.current = selectedSeatIds }, [selectedSeatIds])
  useEffect(() => { selectedZoneRef.current = selectedZoneId }, [selectedZoneId])
  useEffect(() => { toggleSeatRef.current = onToggleSeat }, [onToggleSeat])
  useEffect(() => { selectZoneRef.current = onSelectZone }, [onSelectZone])
  useEffect(() => { unavailableRef.current = onUnavailable }, [onUnavailable])

  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    let renderer: THREE.WebGLRenderer
    try { renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' }) } catch { unavailableRef.current(); return }
    const mobile = window.matchMedia('(max-width: 600px)').matches
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    renderer.setPixelRatio(Math.min(devicePixelRatio, mobile ? 1.2 : 1.65))
    renderer.setSize(host.clientWidth, host.clientHeight, false)
    renderer.outputColorSpace = THREE.SRGBColorSpace
    renderer.shadowMap.enabled = !mobile
    renderer.shadowMap.type = THREE.PCFShadowMap
    renderer.domElement.className = 'venue-3d-canvas'
    renderer.domElement.setAttribute('role', 'img')
    renderer.domElement.setAttribute('aria-label', labelFor(kind))
    renderer.domElement.tabIndex = 0
    host.appendChild(renderer.domElement)

    const scene = new THREE.Scene()
    const background = kind === 'theatre' ? '#ddd7cf' : kind === 'concert' ? '#dbe4e8' : '#e8e5df'
    scene.background = new THREE.Color(background)
    scene.fog = new THREE.Fog(background, 36, 72)
    const camera = new THREE.PerspectiveCamera(kind === 'museum' ? 46 : 42, host.clientWidth / host.clientHeight, .1, 100)
    const start = kind === 'theatre' ? new THREE.Vector3(16, 12, 22) : kind === 'concert' ? new THREE.Vector3(22, 18, 27) : new THREE.Vector3(22, 20, 24)
    const target = kind === 'theatre' ? new THREE.Vector3(0, 1, -2) : new THREE.Vector3(0, 0, 0)
    camera.position.copy(start)
    const controls = new OrbitControls(camera, renderer.domElement)
    controls.target.copy(target)
    controls.enableDamping = false
    controls.enablePan = false
    controls.minDistance = 9
    controls.maxDistance = 52
    controls.minPolarAngle = .38
    controls.maxPolarAngle = Math.PI / 2.08

    scene.add(new THREE.HemisphereLight('#fffdf7', kind === 'theatre' ? '#4c3f38' : '#697a76', kind === 'theatre' ? 1.65 : 2.2))
    const key = new THREE.DirectionalLight(kind === 'theatre' ? '#ffe2bd' : '#ffffff', kind === 'theatre' ? 2.2 : 2.8)
    key.position.set(10, 24, 15)
    key.castShadow = !mobile
    key.shadow.mapSize.set(mobile ? 512 : 1024, mobile ? 512 : 1024)
    scene.add(key)

    const interactives: Interactive[] = []
    let disposableScreen: THREE.Texture | null = null

    if (kind === 'theatre') {
      addBox(scene, [24, .35, 30], [0, -.25, 0], '#4b4643')
      addBox(scene, [.35, 8, 30], [-12, 3.7, 0], '#70645d')
      addBox(scene, [.35, 8, 30], [12, 3.7, 0], '#70645d')
      addBox(scene, [24, 8, .35], [0, 3.7, 14.8], '#70645d')
      addBox(scene, [18, 1.1, 6], [0, .55, -11.7], '#352f2e', { cast: true })
      addBox(scene, [18.2, 6.7, .45], [0, 4.15, -14.25], '#291c22')
      addBox(scene, [8.7, 5.7, .3], [-4.7, 3.9, -13.85], '#7b1831')
      addBox(scene, [8.7, 5.7, .3], [4.7, 3.9, -13.85], '#7b1831')
      addBox(scene, [20, .18, .18], [0, 7.2, -9.2], palette.metal, { metalness: .6 })
      for (const x of [-8, -4, 0, 4, 8]) {
        const lamp = addCylinder(scene, .2, .55, [x, 6.85, -9], '#172c36')
        lamp.rotation.x = Math.PI / 2
      }
      const rowNames = [...new Set(seats.map((seat) => seat.row))]
      rowNames.forEach((_, rowIndex) => addBox(scene, [20, .32 + rowIndex * .34, 1.18], [0, (rowIndex * .34) / 2, -6.1 + rowIndex * 1.45], rowIndex % 2 ? '#655e59' : '#5d5753'))
      addBox(scene, [1.1, .12, 19], [0, .2, 3], '#b8a98c')
      const baseGeometry = new THREE.BoxGeometry(.62, .18, .58)
      const backGeometry = new THREE.BoxGeometry(.62, .65, .13)
      const material = new THREE.MeshStandardMaterial({ color: '#fff', roughness: .58, vertexColors: true })
      const bases = new THREE.InstancedMesh(baseGeometry, material, seats.length)
      const backs = new THREE.InstancedMesh(backGeometry, material.clone(), seats.length)
      const matrix = new THREE.Matrix4()
      seats.forEach((seat, index) => {
        const rowIndex = Math.max(0, rowNames.indexOf(seat.row))
        const aisle = seat.number > 6 ? .62 : -.62
        const x = (seat.number - 6.5) * 1.05 + aisle
        const z = -6.1 + rowIndex * 1.45
        const y = .46 + rowIndex * .34
        matrix.makeTranslation(x, y, z)
        bases.setMatrixAt(index, matrix)
        matrix.makeTranslation(x, y + .34, z + .24)
        backs.setMatrixAt(index, matrix)
      })
      bases.userData.type = 'seats'; backs.userData.type = 'seats'
      bases.castShadow = !mobile; backs.castShadow = !mobile
      scene.add(bases, backs)
      seatMeshesRef.current = [bases, backs]
      interactives.push({ object: bases, type: 'seat', index: 0 }, { object: backs, type: 'seat', index: 0 })
    }

    if (kind === 'concert') {
      addBox(scene, [34, .5, 38], [0, -.3, 0], '#7b8387')
      addBox(scene, [30, .9, 7], [0, .45, -14], '#202c34', { cast: true })
      addBox(scene, [30, 8, .55], [0, 4, -17], '#17242c')
      disposableScreen = screenTexture()
      const screen = new THREE.Mesh(new THREE.PlaneGeometry(12, 5.8), new THREE.MeshStandardMaterial({ map: disposableScreen, emissive: '#102d3d', emissiveIntensity: .32 }))
      screen.position.set(0, 4.2, -16.65)
      scene.add(screen)
      for (const x of [-14, 14]) {
        addCylinder(scene, .18, 10, [x, 4.4, -14], palette.metal)
        addBox(scene, [1.8, .3, 1], [x, 8.5, -14], '#d8e2e3', { metalness: .5 })
      }
      addBox(scene, [29, .22, .22], [0, 8.5, -14], palette.metal, { metalness: .62 })
      const zoneDepth = zones.length > 1 ? 9 : 18
      zones.forEach((zone, index) => {
        const z = -7 + index * (zoneDepth + 1.2)
        const mesh = addBox(scene, [24, .18, zoneDepth], [0, .05, z], zone.available_capacity ? '#bfece3' : '#aebbc1')
        mesh.userData.zoneIndex = index
        zoneMeshesRef.current.push({ mesh, zone })
        interactives.push({ object: mesh, type: 'zone', index })
        for (const x of [-12.3, 12.3]) for (let post = 0; post < 5; post += 1) addCylinder(scene, .045, .9, [x, .45, z - zoneDepth / 2 + 1 + post * 1.75], palette.metal)
      })
      for (const x of [-13.8, 13.8]) addBox(scene, [.35, 2.4, 29], [x, 1.05, 1], '#4e5b61', { metalness: .35 })
      addBox(scene, [5.6, 2.8, .5], [0, 1.2, 18.2], '#36505c')
    }

    if (kind === 'museum') {
      addBox(scene, [34, .35, 26], [0, -.25, 0], '#ddd7cd')
      addBox(scene, [.35, 5.5, 26], [-17, 2.55, 0], '#f4f1ea')
      addBox(scene, [.35, 5.5, 26], [17, 2.55, 0], '#f4f1ea')
      addBox(scene, [34, 5.5, .35], [0, 2.55, -13], '#f4f1ea')
      addBox(scene, [34, 5.5, .35], [0, 2.55, 13], '#f4f1ea')
      for (const x of [-8.5, 0, 8.5]) {
        addBox(scene, [.28, 4.6, 8.2], [x, 2.15, -7.8], '#f7f4ee')
        addBox(scene, [.28, 4.6, 8.2], [x, 2.15, 7.8], '#f7f4ee')
      }
      for (const [x, z] of [[-12, -7], [-5, -3], [3, -7], [11, -3], [-11, 7], [-2, 7], [7, 5]] as const) {
        addBox(scene, [2.2, .85, 2.2], [x, .34, z], '#c9bfae')
        const sculpture = new THREE.Mesh(new THREE.TorusKnotGeometry(.52, .16, 48, 8), new THREE.MeshStandardMaterial({ color: x % 2 ? '#b36d48' : '#3c7b78', roughness: .5 }))
        sculpture.position.set(x, 1.45, z)
        sculpture.scale.set(.7, .7, .7)
        sculpture.castShadow = !mobile
        scene.add(sculpture)
      }
      const artColors = ['#ba614d', '#397d86', '#d2a344', '#716294']
      for (let index = 0; index < 4; index += 1) {
        const frame = addBox(scene, [3.2, 2.2, .18], [-11 + index * 7.2, 2.7, -12.72], '#20333d')
        addBox(frame, [2.7, 1.7, .08], [0, 0, .14], artColors[index])
      }
      for (const x of [-12, -4, 4, 12]) {
        const light = new THREE.PointLight('#fff3dd', mobile ? .35 : .7, 11)
        light.position.set(x, 5.5, 0)
        scene.add(light)
      }
    }

    const updateColors = () => {
      if (kind === 'theatre' && seatMeshesRef.current.length) {
        seats.forEach((seat, index) => {
          const color = selectedSeatsRef.current.includes(seat.id) ? palette.turquoise : seat.available ? palette.ink : palette.occupied
          seatMeshesRef.current.forEach((mesh) => mesh.setColorAt(index, color))
        })
        seatMeshesRef.current.forEach((mesh) => { if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true })
      }
      if (kind === 'concert') zoneMeshesRef.current.forEach(({ mesh, zone }) => {
        const material = mesh.material as THREE.MeshStandardMaterial
        material.color.set(selectedZoneRef.current === zone.id ? '#00c2a5' : zone.available_capacity ? '#bfece3' : '#aebbc1')
      })
    }
    updateColors()
    const render = () => renderer.render(scene, camera)
    renderRef.current = render
    controls.addEventListener('change', render)
    render()
    setReady(true)

    const reset = () => { camera.position.copy(start); controls.target.copy(target); controls.update(); render() }
    const zoom = (factor: number) => {
      const offset = camera.position.clone().sub(controls.target).multiplyScalar(factor)
      camera.position.copy(controls.target).add(offset.setLength(Math.max(controls.minDistance, Math.min(controls.maxDistance, offset.length()))))
      controls.update(); render()
    }
    cameraApi.current = { reset, zoom }

    const raycaster = new THREE.Raycaster()
    const pointer = new THREE.Vector2()
    const hitAt = (event: PointerEvent) => {
      const bounds = renderer.domElement.getBoundingClientRect()
      pointer.set((event.clientX - bounds.left) / bounds.width * 2 - 1, -((event.clientY - bounds.top) / bounds.height * 2 - 1))
      raycaster.setFromCamera(pointer, camera)
      return raycaster.intersectObjects(interactives.map((item) => item.object), false)[0]
    }
    const onMove = (event: PointerEvent) => {
      const hit = hitAt(event)
      if (!hit) { setHover(null); renderer.domElement.style.cursor = 'grab'; return }
      if (hit.object.userData.type === 'seats' && hit.instanceId !== undefined) {
        const seat = seats[hit.instanceId]
        setHover(`${seat.zone_name} · Fila ${seat.row} · Asiento ${seat.number} · S/ ${seat.price.toFixed(2)} · ${seat.available ? 'Disponible' : 'Ocupado'}`)
        renderer.domElement.style.cursor = seat.available ? 'pointer' : 'not-allowed'
      } else {
        const index = hit.object.userData.zoneIndex as number
        const zone = zones[index]
        setHover(`${zone.name} · S/ ${zone.price.toFixed(2)} · ${zone.available_capacity} disponibles`)
        renderer.domElement.style.cursor = zone.available_capacity ? 'pointer' : 'not-allowed'
      }
    }
    const onDown = (event: PointerEvent) => {
      const hit = hitAt(event)
      if (!hit) return
      if (hit.object.userData.type === 'seats' && hit.instanceId !== undefined) {
        const seat = seats[hit.instanceId]
        if (seat.available) toggleSeatRef.current?.(seat)
      } else {
        const zone = zones[hit.object.userData.zoneIndex as number]
        if (zone?.available_capacity) selectZoneRef.current?.(zone.id)
      }
    }
    renderer.domElement.addEventListener('pointermove', onMove)
    renderer.domElement.addEventListener('pointerdown', onDown)
    const observer = new ResizeObserver(() => {
      if (!host.clientWidth || !host.clientHeight) return
      camera.aspect = host.clientWidth / host.clientHeight; camera.updateProjectionMatrix(); renderer.setSize(host.clientWidth, host.clientHeight, false); render()
    })
    observer.observe(host)
    const onContextLost = (event: Event) => { event.preventDefault(); unavailableRef.current() }
    renderer.domElement.addEventListener('webglcontextlost', onContextLost)

    return () => {
      observer.disconnect(); controls.removeEventListener('change', render); controls.dispose()
      renderer.domElement.removeEventListener('pointermove', onMove); renderer.domElement.removeEventListener('pointerdown', onDown); renderer.domElement.removeEventListener('webglcontextlost', onContextLost)
      scene.traverse((object) => { if (object instanceof THREE.Mesh || object instanceof THREE.Line) { object.geometry.dispose(); const materials = Array.isArray(object.material) ? object.material : [object.material]; materials.forEach((material) => material.dispose()) } })
      disposableScreen?.dispose(); renderer.dispose(); renderer.domElement.remove(); renderRef.current = null; seatMeshesRef.current = []; zoneMeshesRef.current = []; cameraApi.current = null
    }
  }, [kind, seats, zones])

  useEffect(() => {
    if (kind === 'theatre' && seatMeshesRef.current.length) {
      seats.forEach((seat, index) => {
        const color = selectedSeatIds.includes(seat.id) ? palette.turquoise : seat.available ? palette.ink : palette.occupied
        seatMeshesRef.current.forEach((mesh) => mesh.setColorAt(index, color))
      })
      seatMeshesRef.current.forEach((mesh) => { if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true })
    }
    if (kind === 'concert') zoneMeshesRef.current.forEach(({ mesh, zone }) => (mesh.material as THREE.MeshStandardMaterial).color.set(selectedZoneId === zone.id ? '#00c2a5' : zone.available_capacity ? '#bfece3' : '#aebbc1'))
    renderRef.current?.()
  }, [kind, seats, selectedSeatIds, selectedZoneId])

  return <div className={`venue-3d-shell venue-3d-${kind}`}>
    <div className="venue-3d-stage">
      <div className="venue-3d-toolbar" role="group" aria-label="Controles de cámara 3D"><button type="button" aria-label="Acercar cámara" onClick={() => cameraApi.current?.zoom(.82)}>+</button><button type="button" aria-label="Alejar cámara" onClick={() => cameraApi.current?.zoom(1.2)}>−</button><button type="button" onClick={() => cameraApi.current?.reset()}>Restablecer</button></div>
      <div ref={hostRef} className="venue-3d-host" aria-busy={!ready} />
      {!ready && <div className="venue-3d-loading" role="status"><span className="spinner" />Preparando ambiente 3D…</div>}
      <div className="venue-3d-hint">Arrastra para explorar · Pellizca o desplaza para acercar</div>
      {hover && <div className="venue-3d-tooltip" role="status">{hover}</div>}
    </div>
    <p className="venue-3d-note">{kind === 'museum' ? 'Recorrido orientativo de un museo ficticio. Las salas no se reservan.' : 'Representación 3D aproximada de un recinto ficticio. Solo el inventario real de esta función permite reservar.'}</p>
  </div>
}
