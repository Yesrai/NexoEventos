import * as THREE from 'three'
import { box, carpetTexture, cylinder, labelSprite, lightBeam, plane, plasterTexture, std, woodTexture } from './venue3d-kit'
import { zoneColors, type VenueBuild, type VenueContext, type VenueSeat } from './venue3d-types'

const PITCH = .6
const AISLE = 1.2
const ROW_PITCH = 1.05
const RISE = .2
const HEIGHT = 8
const FIRST_ROW_Z = -2

function exitSign() {
  const canvas = document.createElement('canvas')
  canvas.width = 256
  canvas.height = 96
  const context = canvas.getContext('2d')
  if (context) {
    context.fillStyle = '#0c6b3a'
    context.fillRect(0, 0, 256, 96)
    context.fillStyle = '#eafff2'
    context.font = '700 52px Arial'
    context.textAlign = 'center'
    context.textBaseline = 'middle'
    context.fillText('SALIDA', 128, 50)
  }
  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  return texture
}

export function buildTheatre({ scene, mobile }: VenueContext, seats: VenueSeat[]): VenueBuild {
  const rows = [...new Set(seats.map((seat) => seat.row))]
  const columns = Math.max(12, ...seats.map((seat) => seat.number))
  const half = Math.floor(columns / 2)
  const width = Math.max(12.6, columns * PITCH + AISLE + 4.4)
  const backZ = FIRST_ROW_Z + rows.length * ROW_PITCH + 2.8
  const stageBackZ = -11.4
  const prosceniumZ = -4.7
  const length = backZ - stageBackZ
  const midZ = (backZ + stageBackZ) / 2
  const rowTop = (index: number) => .1 + index * RISE
  const colors = zoneColors(seats.map((seat) => ({ id: seat.zone_id, price: seat.price })))

  const carpet = std({ map: carpetTexture('#5b2630', [width / 2, ROW_PITCH / 2]), roughness: 1 })
  const floorCarpet = std({ map: carpetTexture('#5b2630', [width / 2, length / 2], 9), roughness: 1 })
  const wallWine = std({ map: plasterTexture('#5a2f3d', [length / 3, 2]), roughness: .95 })
  const wood = std({ map: woodTexture('#7a5232', [length / 3, 1], 4), roughness: .55, metalness: .05 })
  const darkWood = std({ color: '#3a2619', roughness: .6 })
  const stageWood = std({ map: woodTexture('#5f4128', [4, 3], 8), roughness: .45, metalness: .04 })
  const gold = std({ color: '#c8a45a', roughness: .35, metalness: .85 })
  const velvet = std({ color: '#86172a', roughness: .92 })
  const ceilingMaterial = std({ color: '#2e1d25', roughness: .95 })
  const lampMaterial = std({ color: '#2a2220', emissive: '#ffd49a', emissiveIntensity: 1.6 })
  const metal = std({ color: '#262b30', roughness: .4, metalness: .8 })

  // Superficies: caras hacia el interior; desde fuera quedan invisibles (corte arquitectónico).
  plane(scene, width, length, [0, 0, midZ], [-Math.PI / 2, 0, 0], floorCarpet)
  plane(scene, width, length, [0, HEIGHT, midZ], [Math.PI / 2, 0, 0], ceilingMaterial)
  plane(scene, length, HEIGHT, [-width / 2, HEIGHT / 2, midZ], [0, Math.PI / 2, 0], wallWine)
  plane(scene, length, HEIGHT, [width / 2, HEIGHT / 2, midZ], [0, -Math.PI / 2, 0], wallWine)
  plane(scene, width, HEIGHT, [0, HEIGHT / 2, backZ], [0, Math.PI, 0], wallWine)
  plane(scene, width, HEIGHT, [0, HEIGHT / 2, stageBackZ], [0, 0, 0], std({ color: '#15161d', roughness: 1 }))
  plane(scene, length, 2.7, [-width / 2 + .02, 1.35, midZ], [0, Math.PI / 2, 0], wood)
  plane(scene, length, 2.7, [width / 2 - .02, 1.35, midZ], [0, -Math.PI / 2, 0], wood)
  plane(scene, width, 2.7, [0, 1.35, backZ - .02], [0, Math.PI, 0], wood)

  // Pilastras acústicas y apliques laterales.
  const sconces: THREE.Vector3[] = []
  for (let z = stageBackZ + 3; z < backZ - 1; z += 3.4) {
    for (const side of [-1, 1]) {
      box(scene, [.24, HEIGHT - 1.2, .5], [side * (width / 2 - .12), (HEIGHT - 1.2) / 2 + .2, z], wood, { cast: false })
      box(scene, [.06, .5, .22], [side * (width / 2 - .31), 4.1, z], lampMaterial)
      sconces.push(new THREE.Vector3(side * (width / 2 - .5), 4.1, z))
    }
  }

  // Techo artesonado con vigas y paneles luminosos.
  for (let z = stageBackZ + 2; z < backZ; z += 3.4) box(scene, [width, .45, .3], [0, HEIGHT - .22, z], darkWood)
  for (let z = FIRST_ROW_Z - 1; z < backZ - 1; z += 3.4) for (const x of [-width / 4, width / 4]) box(scene, [width / 2 - 1.2, .05, 1.6], [x, HEIGHT - .1, z + 1.7], lampMaterial)

  // Escenario con proscenio, telón, cortinas y trasfondo.
  const stageTop = 1.15
  const stageDepth = prosceniumZ - stageBackZ
  box(scene, [width - .1, stageTop, stageDepth], [0, stageTop / 2, (prosceniumZ + stageBackZ) / 2], stageWood)
  plane(scene, width - .1, stageDepth, [0, stageTop + .01, (prosceniumZ + stageBackZ) / 2], [-Math.PI / 2, 0, 0], stageWood)
  box(scene, [9.8, stageTop, 1.4], [0, stageTop / 2, prosceniumZ + .7], stageWood)
  box(scene, [10.2, .06, .08], [0, stageTop + .03, prosceniumZ + 1.4], gold)
  const openingHalf = 4.9
  const openingHeight = 5.9
  const wallSide = (width / 2 - openingHalf)
  for (const side of [-1, 1]) box(scene, [wallSide, HEIGHT, .6], [side * (openingHalf + wallSide / 2), HEIGHT / 2, prosceniumZ], wallWine, { cast: true })
  box(scene, [openingHalf * 2, HEIGHT - openingHeight, .6], [0, openingHeight + (HEIGHT - openingHeight) / 2, prosceniumZ], wallWine)
  box(scene, [openingHalf * 2 + .5, .24, .72], [0, openingHeight, prosceniumZ + .05], gold)
  for (const side of [-1, 1]) box(scene, [.24, openingHeight, .72], [side * openingHalf, openingHeight / 2, prosceniumZ + .05], gold)
  // Cenefa y cortinas drapeadas con pliegues.
  box(scene, [openingHalf * 2, 1.1, .5], [0, openingHeight - .5, prosceniumZ + .3], velvet)
  for (const side of [-1, 1]) {
    const drape = new THREE.PlaneGeometry(3.1, openingHeight - 1.3, 46, 1)
    const positions = drape.attributes.position
    for (let index = 0; index < positions.count; index += 1) positions.setZ(index, Math.sin(positions.getX(index) * 7) * .13)
    drape.computeVertexNormals()
    const curtain = new THREE.Mesh(drape, new THREE.MeshStandardMaterial({ color: '#86172a', roughness: .92, side: THREE.DoubleSide }))
    curtain.position.set(side * (openingHalf - 1.55), stageTop + (openingHeight - 1.3) / 2, prosceniumZ + .1)
    scene.add(curtain)
  }
  // Escena: sillón, atril y reflector.
  cylinder(scene, .018, .018, 1.55, [1.6, stageTop + .78, -7.2], metal, 8)
  cylinder(scene, .16, .16, .04, [1.6, stageTop + .02, -7.2], metal, 16)
  box(scene, [.32, .55, .32], [-2.2, stageTop + .28, -7.6], std({ color: '#1d4a5e', roughness: .7 }))
  box(scene, [.9, .9, .5], [-.4, stageTop + .45, -8.8], darkWood)

  // Barras de iluminación con reflectores y haces suaves.
  const beamColors = ['#ffe6bd', '#ffd1a1', '#cfe3ff', '#ffd1a1', '#ffe6bd']
  for (const z of [-6.2, -9.2]) {
    box(scene, [width - 3, .14, .14], [0, 7, z], metal)
    for (let index = 0; index < 5; index += 1) {
      const x = -4.8 + index * 2.4
      const lamp = cylinder(scene, .2, .26, .5, [x, 6.7, z], std({ color: '#171a1d', roughness: .5, metalness: .7 }), 14)
      lamp.rotation.x = z < -7 ? .35 : .5
      const lens = new THREE.Mesh(new THREE.CircleGeometry(.19, 14), new THREE.MeshBasicMaterial({ color: beamColors[index] }))
      lens.position.set(x, 6.52, z + .14)
      lens.rotation.x = Math.PI / 2 + (z < -7 ? .35 : .5)
      scene.add(lens)
      if (!mobile || index % 2 === 0) lightBeam(scene, new THREE.Vector3(x, 6.55, z), new THREE.Vector3(x * .55, stageTop, -7 + (index - 2) * .3), beamColors[index], 1.0, .075)
    }
  }

  // Suelo escalonado de butacas.
  rows.forEach((_, index) => box(scene, [width, rowTop(index), ROW_PITCH], [0, rowTop(index) / 2, FIRST_ROW_Z + index * ROW_PITCH], carpet))
  const lastIndex = Math.max(0, rows.length - 1)
  const tail = backZ - (FIRST_ROW_Z + lastIndex * ROW_PITCH + ROW_PITCH / 2)
  box(scene, [width, rowTop(lastIndex), tail], [0, rowTop(lastIndex) / 2, FIRST_ROW_Z + lastIndex * ROW_PITCH + ROW_PITCH / 2 + tail / 2], carpet)
  // Alfombra central dorada y luces de pasillo.
  const stepLights = new THREE.InstancedMesh(new THREE.BoxGeometry(.08, .05, .3), lampMaterial, rows.length * 2)
  const dummy = new THREE.Object3D()
  rows.forEach((_, index) => {
    for (const [slot, side] of [[0, -1], [1, 1]] as const) {
      dummy.position.set(side * (columns * PITCH / 2 + AISLE / 2 + .55), rowTop(index) + .03, FIRST_ROW_Z + index * ROW_PITCH - .1)
      dummy.updateMatrix()
      stepLights.setMatrixAt(index * 2 + slot, dummy.matrix)
    }
  })
  scene.add(stepLights)

  // Butacas instanciadas: asiento + respaldo + reposabrazos.
  const baseGeometry = new THREE.BoxGeometry(.5, .13, .5)
  const backGeometry = new THREE.BoxGeometry(.5, .56, .09)
  const armGeometry = new THREE.BoxGeometry(.05, .07, .46)
  const seatMaterial = new THREE.MeshStandardMaterial({ color: '#ffffff', roughness: .85, metalness: 0 })
  const bases = new THREE.InstancedMesh(baseGeometry, seatMaterial, seats.length)
  const backs = new THREE.InstancedMesh(backGeometry, seatMaterial.clone(), seats.length)
  const arms = new THREE.InstancedMesh(armGeometry, darkWood, seats.length * 2)
  bases.userData.kind = 'seat'
  backs.userData.kind = 'seat'
  const seatPosition = (seat: VenueSeat) => {
    const rowIndex = Math.max(0, rows.indexOf(seat.row))
    const side = seat.number > half ? 1 : -1
    return new THREE.Vector3((seat.number - (columns + 1) / 2) * PITCH + side * AISLE / 2, rowTop(rowIndex) + .38, FIRST_ROW_Z + rowIndex * ROW_PITCH)
  }
  const matrix = new THREE.Matrix4()
  const quaternion = new THREE.Quaternion()
  const tilt = new THREE.Quaternion().setFromEuler(new THREE.Euler(-.14, 0, 0))
  const unit = new THREE.Vector3(1, 1, 1)
  const draw = (selected: number[]) => {
    seats.forEach((seat, index) => {
      const position = seatPosition(seat)
      const chosen = selected.includes(seat.id)
      const lift = chosen ? .05 : 0
      matrix.compose(new THREE.Vector3(position.x, position.y + lift, position.z), quaternion.identity(), unit)
      bases.setMatrixAt(index, matrix)
      matrix.compose(new THREE.Vector3(position.x, position.y + .3 + lift, position.z + .22), tilt, unit)
      backs.setMatrixAt(index, matrix)
      for (const [slot, offset] of [[0, -.28], [1, .28]] as const) {
        matrix.compose(new THREE.Vector3(position.x + offset, position.y + .22, position.z), quaternion.identity(), unit)
        arms.setMatrixAt(index * 2 + slot, matrix)
      }
      const color = new THREE.Color(chosen ? '#00e0bd' : seat.available ? colors.get(seat.zone_id) ?? '#3d73a8' : '#98a1a6')
      bases.setColorAt(index, color)
      backs.setColorAt(index, color)
    })
    bases.instanceMatrix.needsUpdate = true
    backs.instanceMatrix.needsUpdate = true
    arms.instanceMatrix.needsUpdate = true
    if (bases.instanceColor) bases.instanceColor.needsUpdate = true
    if (backs.instanceColor) backs.instanceColor.needsUpdate = true
  }
  bases.castShadow = !mobile
  backs.castShadow = !mobile
  draw([])
  scene.add(bases, backs, arms)

  rows.forEach((row, index) => {
    for (const side of [-1, 1]) {
      const badge = labelSprite(row, { badge: true, scale: .4, background: 'rgba(200,164,90,.95)', color: '#2a1a08' })
      if (badge) { badge.position.set(side * (columns * PITCH / 2 + AISLE / 2 + .1 + .2), rowTop(index) + .95, FIRST_ROW_Z + index * ROW_PITCH); scene.add(badge) }
    }
  })

  // Puertas con señalización de salida.
  const signTexture = exitSign()
  for (const x of [-width / 2 + 2.2, width / 2 - 2.2]) {
    box(scene, [1.9, 2.5, .1], [x, rowTop(lastIndex) + 1.25, backZ - .06], darkWood)
    box(scene, [.9, 2.3, .08], [x - .46, rowTop(lastIndex) + 1.25, backZ - .12], wood)
    box(scene, [.9, 2.3, .08], [x + .46, rowTop(lastIndex) + 1.25, backZ - .12], wood)
    const sign = new THREE.Mesh(new THREE.PlaneGeometry(.9, .34), new THREE.MeshBasicMaterial({ map: signTexture }))
    sign.position.set(x, rowTop(lastIndex) + 3.1, backZ - .1)
    sign.rotation.y = Math.PI
    scene.add(sign)
  }
  // Cabina de proyección/iluminación.
  box(scene, [4.2, 1.4, .2], [0, 6.1, backZ - .12], std({ color: '#10181d', roughness: .3, metalness: .2 }))

  // Iluminación: ambiente cálido, focos hacia el escenario y luz sobre el público.
  scene.add(new THREE.HemisphereLight('#ffe9d2', '#3a2024', .9))
  for (const [x, z] of [[-3.5, 1.5], [3.5, 1.5], [0, 5]] as const) {
    const point = new THREE.PointLight('#ffd9a8', 14, 14, 2)
    point.position.set(x, HEIGHT - 1.2, z)
    scene.add(point)
  }
  const wash = new THREE.SpotLight('#ffeacb', 140, 22, .5, .8, 1.6)
  wash.position.set(0, HEIGHT - .8, 0)
  wash.target.position.set(0, stageTop, -8.5)
  scene.add(wash, wash.target)
  for (const point of sconces.filter((_, index) => index % 3 === 0)) {
    const light = new THREE.PointLight('#ffc98a', 7, 7, 2)
    light.position.copy(point)
    scene.add(light)
  }

  const bounds = new THREE.Box3(new THREE.Vector3(-width / 2 + .7, 1.0, stageBackZ + 1), new THREE.Vector3(width / 2 - .7, HEIGHT - .7, backZ - .7))
  const seatTop = rowTop(lastIndex)
  const views = [
    { id: 'sala', label: 'Desde la sala', position: new THREE.Vector3(0, seatTop + 4.6, backZ - .9), target: new THREE.Vector3(0, 1.2, -3.5) },
    { id: 'platea', label: 'Platea', position: new THREE.Vector3(0, 2.6, FIRST_ROW_Z - 1), target: new THREE.Vector3(0, 2.4, -8) },
    { id: 'general', label: 'Vista general', position: new THREE.Vector3(width / 2 - 1.6, HEIGHT - 1.4, backZ - 1.2), target: new THREE.Vector3(-1, 1.4, -4) },
  ]

  return {
    views,
    background: '#17100f',
    minDistance: 2.5,
    maxDistance: 24,
    minPolar: .35,
    maxPolar: Math.PI / 1.7,
    bounds,
    pickables: [bases, backs],
    describe: (hit) => {
      if (hit.instanceId === undefined) return null
      const seat = seats[hit.instanceId]
      if (!seat) return null
      return { text: `${seat.zone_name} · Fila ${seat.row} · Asiento ${seat.number} · S/ ${seat.price.toFixed(2)} · ${seat.available ? 'Disponible' : 'Ocupado'}`, enabled: seat.available, seat }
    },
    refresh: ({ selectedSeatIds }) => draw(selectedSeatIds),
    legend: [...new Map(seats.map((seat) => [seat.zone_id, seat])).values()].sort((a, b) => a.price - b.price).map((seat) => ({ label: `${seat.zone_name} · S/ ${seat.price.toFixed(2)}`, color: colors.get(seat.zone_id) ?? '#3d73a8' })),
  }
}
