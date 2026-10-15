import * as THREE from 'three'
import { box, concreteTexture, cylinder, labelSprite, lightBeam, plane, screenTexture, seededRandom, skyGradient, std } from './venue3d-kit'
import type { VenueBuild, VenueContext, VenueZone } from './venue3d-types'

const FLOOR_HALF_WIDTH = 15
const STAGE_Z = -13
const FIRST_ZONE_Z = -2.5
const FLOOR_DEPTH = 27

const zoneHues = ['#c9892b', '#7a5aa6', '#4f8a6a', '#b5523f']

function windowsTexture() {
  const canvas = document.createElement('canvas')
  canvas.width = 128
  canvas.height = 256
  const context = canvas.getContext('2d')
  if (context) {
    const random = seededRandom(21)
    context.fillStyle = '#0c0f1c'
    context.fillRect(0, 0, 128, 256)
    for (let y = 8; y < 250; y += 14) for (let x = 6; x < 120; x += 14) {
      if (random() > .55) { context.fillStyle = random() > .3 ? '#ffd98a' : '#9fd8ff'; context.fillRect(x, y, 7, 8) }
    }
  }
  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  return texture
}

function truss(parent: THREE.Object3D, length: number, position: [number, number, number], rotation: [number, number, number] = [0, 0, 0], material: THREE.Material) {
  const group = new THREE.Group()
  const lattice = new THREE.Mesh(new THREE.BoxGeometry(length, .5, .5, Math.max(2, Math.round(length / .6)), 1, 1), new THREE.MeshBasicMaterial({ color: '#8f9aa3', wireframe: true }))
  group.add(lattice)
  for (const y of [-.25, .25]) for (const z of [-.25, .25]) {
    const chord = new THREE.Mesh(new THREE.BoxGeometry(length, .06, .06), material)
    chord.position.set(0, y, z)
    group.add(chord)
  }
  group.position.set(...position)
  group.rotation.set(...rotation)
  parent.add(group)
  return group
}

export function buildConcert({ scene, mobile }: VenueContext, zones: VenueZone[]): VenueBuild {
  scene.fog = new THREE.FogExp2('#190f2e', mobile ? .014 : .011)
  const metal = std({ color: '#aab3ba', roughness: .35, metalness: .85 })
  const black = std({ color: '#0f1317', roughness: .5, metalness: .4 })
  const stageFloor = std({ color: '#171c22', roughness: .35, metalness: .3 })
  const fence = std({ color: '#2a323a', roughness: .55, metalness: .5 })
  const ground = std({ map: concreteTexture('#1a1b24', [40, 40], 19), roughness: 1 })
  const turf = std({ map: concreteTexture('#223326', [10, 12], 4), roughness: 1 })

  // Cielo nocturno, horizonte urbano, árboles y estrellas.
  const dome = new THREE.Mesh(new THREE.SphereGeometry(150, 24, 16), new THREE.MeshBasicMaterial({ map: skyGradient('#070b1f', '#4a2561', '#1d1a30'), side: THREE.BackSide, fog: false }))
  scene.add(dome)
  const random = seededRandom(44)
  const starPositions: number[] = []
  for (let index = 0; index < 260; index += 1) {
    const angle = random() * Math.PI * 2
    const lift = .25 + random() * .75
    starPositions.push(Math.cos(angle) * 140 * Math.sqrt(1 - lift * lift), lift * 140, Math.sin(angle) * 140 * Math.sqrt(1 - lift * lift))
  }
  const starGeometry = new THREE.BufferGeometry()
  starGeometry.setAttribute('position', new THREE.Float32BufferAttribute(starPositions, 3))
  scene.add(new THREE.Points(starGeometry, new THREE.PointsMaterial({ color: '#ffffff', size: 1.1, sizeAttenuation: false, fog: false })))
  const windows = windowsTexture()
  windows.repeat.set(1, 1)
  for (let index = 0; index < 26; index += 1) {
    const angle = index / 26 * Math.PI * 2
    const height = 14 + random() * 28
    const tower = new THREE.Mesh(new THREE.BoxGeometry(9 + random() * 7, height, 9 + random() * 7), new THREE.MeshStandardMaterial({ map: windows, emissive: '#ffffff', emissiveMap: windows, emissiveIntensity: .55, roughness: 1 }))
    tower.position.set(Math.cos(angle) * 96, height / 2 - 2, Math.sin(angle) * 96)
    scene.add(tower)
  }
  plane(scene, 360, 360, [0, -.02, 0], [-Math.PI / 2, 0, 0], ground)
  const treeGeometry = new THREE.ConeGeometry(2.1, 6.5, 7)
  const trunkGeometry = new THREE.CylinderGeometry(.28, .36, 2, 6)
  const treeCount = mobile ? 34 : 64
  const crowns = new THREE.InstancedMesh(treeGeometry, std({ color: '#12301f', roughness: 1 }), treeCount)
  const trunks = new THREE.InstancedMesh(trunkGeometry, std({ color: '#2b1d14', roughness: 1 }), treeCount)
  const dummy = new THREE.Object3D()
  for (let index = 0; index < treeCount; index += 1) {
    const angle = index / treeCount * Math.PI * 2 + random() * .08
    const radius = 56 + random() * 16
    const x = Math.cos(angle) * radius
    const z = Math.sin(angle) * radius
    const scale = .8 + random() * .7
    dummy.position.set(x, 1 + 3.25 * scale, z); dummy.scale.setScalar(scale); dummy.updateMatrix(); crowns.setMatrixAt(index, dummy.matrix)
    dummy.position.set(x, 1 * scale, z); dummy.updateMatrix(); trunks.setMatrixAt(index, dummy.matrix)
  }
  scene.add(crowns, trunks)

  // Explanada del recinto.
  plane(scene, FLOOR_HALF_WIDTH * 2 + 8, 72, [0, .0, 6], [-Math.PI / 2, 0, 0], std({ map: concreteTexture('#26272f', [8, 14], 2), roughness: .95 }))
  plane(scene, FLOOR_HALF_WIDTH * 2 + 3, FLOOR_DEPTH + 7, [0, .01, FIRST_ZONE_Z + FLOOR_DEPTH / 2 - 1.5], [-Math.PI / 2, 0, 0], turf)

  // Escenario, trasfondo y pantallas LED.
  const stageHeight = 1.7
  const stageDepth = 11
  box(scene, [26, stageHeight, stageDepth], [0, stageHeight / 2, STAGE_Z], stageFloor, { cast: true })
  box(scene, [26.2, .12, .12], [0, stageHeight + .02, STAGE_Z + stageDepth / 2 + .02], std({ color: '#2f6bff', emissive: '#4d7dff', emissiveIntensity: 2 }))
  const mainScreenTexture = screenTexture('NEXO', 'ESCENA DEMO')
  const ledMaterial = new THREE.MeshStandardMaterial({ map: mainScreenTexture, emissive: '#ffffff', emissiveMap: mainScreenTexture, emissiveIntensity: 1.05, roughness: .4 })
  box(scene, [27, 13, .8], [0, stageHeight + 6.5, STAGE_Z - stageDepth / 2 - .3], black)
  const mainScreen = new THREE.Mesh(new THREE.PlaneGeometry(14, 7.4), ledMaterial)
  mainScreen.position.set(0, stageHeight + 7.4, STAGE_Z - stageDepth / 2 + .12)
  scene.add(mainScreen)
  for (const side of [-1, 1]) {
    const wing = new THREE.Mesh(new THREE.PlaneGeometry(5, 7.4), ledMaterial)
    wing.position.set(side * 10, stageHeight + 7.4, STAGE_Z - stageDepth / 2 + .12)
    scene.add(wing)
  }
  // Estructura de truss sobre el escenario y torres.
  for (const x of [-13.2, 13.2]) for (const z of [STAGE_Z - 5, STAGE_Z + 5]) truss(scene, 12.5, [x, stageHeight + 6.2, z], [0, 0, Math.PI / 2], metal)
  for (const z of [STAGE_Z - 5, STAGE_Z - 1, STAGE_Z + 5]) truss(scene, 27, [0, stageHeight + 12.4, z], [0, 0, 0], metal)
  for (const x of [-13.2, 13.2]) truss(scene, 10.5, [x, stageHeight + 12.4, STAGE_Z], [0, Math.PI / 2, 0], metal)
  truss(scene, 26, [0, stageHeight + 10.1, STAGE_Z + 5], [0, 0, 0], metal)

  // Cabezales móviles con haces de color.
  const hues = ['#c9892b', '#7a5aa6', '#4f8a6a', '#b5523f', '#7a5aa6', '#c9892b']
  const rigZ = [STAGE_Z + 5, STAGE_Z - 1]
  rigZ.forEach((z, rigIndex) => {
    for (let index = 0; index < 7; index += 1) {
      const x = -10.5 + index * 3.5
      const y = rigIndex === 0 ? stageHeight + 9.7 : stageHeight + 12
      cylinder(scene, .32, .4, .75, [x, y, z], black, 12)
      const lens = new THREE.Mesh(new THREE.CircleGeometry(.26, 12), new THREE.MeshBasicMaterial({ color: hues[index % hues.length] }))
      lens.position.set(x, y - .38, z); lens.rotation.x = Math.PI / 2
      scene.add(lens)
      if (!mobile || index % 2 === 0) {
        const aimX = x * .35 + (index % 2 ? -3 : 3) * (rigIndex ? 1.4 : .6)
        lightBeam(scene, new THREE.Vector3(x, y - .4, z), new THREE.Vector3(aimX, rigIndex ? .2 : 1.2, rigIndex ? 9 : 5 + index % 3 * 2), hues[(index + rigIndex * 2) % hues.length], rigIndex ? 1.5 : 1.1, .1)
      }
    }
  })
  // Línea de PA colgada, subwoofers, monitores y back line.
  for (const side of [-1, 1]) {
    const hang = 14.8 * side
    for (let index = 0; index < 8; index += 1) {
      const cabinet = box(scene, [1.5, .7, .95], [hang, stageHeight + 11.2 - index * .74, STAGE_Z + 4.4 + index * .08], black)
      cabinet.rotation.x = -.04 * index
      box(scene, [1.3, .45, .02], [hang, stageHeight + 11.2 - index * .74, STAGE_Z + 4.9 + index * .1], std({ color: '#2d343b', roughness: .9 }))
    }
    for (const dx of [0, 1.6]) for (let tier = 0; tier < 2; tier += 1) box(scene, [1.5, 1.2, 1.2], [side * (11 + dx), stageHeight + .6 + tier * 1.2, STAGE_Z + 6.8], black)
  }
  for (const x of [-4, -1, 2, 5]) {
    const wedge = box(scene, [1.1, .45, .7], [x, stageHeight + .22, STAGE_Z + 4.2], black)
    wedge.rotation.x = .4
  }
  // Batería, amplificadores, teclados y micrófonos.
  box(scene, [4.2, .35, 3.2], [0, stageHeight + .17, STAGE_Z - 2], std({ color: '#1f242b', roughness: .6 }))
  cylinder(scene, .55, .55, .6, [0, stageHeight + .65, STAGE_Z - 2], std({ color: '#b82d3d', roughness: .35, metalness: .25 }), 20)
  for (const x of [-1.3, 1.3]) cylinder(scene, .38, .38, .4, [x, stageHeight + 1.0, STAGE_Z - 2.4], std({ color: '#b82d3d', roughness: .35, metalness: .25 }), 16)
  for (const x of [-1.6, 1.6]) { const cymbal = cylinder(scene, .5, .5, .02, [x, stageHeight + 1.7, STAGE_Z - 2.7], std({ color: '#d4a93a', roughness: .25, metalness: .9 }), 16); cymbal.rotation.z = x * .06 }
  for (const x of [-8, 8]) box(scene, [1.3, 1.8, .8], [x, stageHeight + .9, STAGE_Z - 3.5], black)
  box(scene, [2, .85, .6], [6, stageHeight + .45, STAGE_Z + 1], black)
  for (const x of [-5, -1.5, 2.5]) {
    cylinder(scene, .02, .02, 1.7, [x, stageHeight + .85, STAGE_Z + 3.2], metal, 6)
    cylinder(scene, .06, .06, .16, [x, stageHeight + 1.75, STAGE_Z + 3.2], black, 8)
  }

  // Foso, vallas y límites de la explanada.
  const barrierZ = FIRST_ZONE_Z - 1.2
  box(scene, [FLOOR_HALF_WIDTH * 2, .08, .08], [0, 1.05, barrierZ], fence)
  for (let x = -FLOOR_HALF_WIDTH; x <= FLOOR_HALF_WIDTH; x += 1.5) box(scene, [.08, 1.1, .08], [x, .55, barrierZ], fence)
  const wallLength = FLOOR_DEPTH + 7
  const wallMid = FIRST_ZONE_Z + FLOOR_DEPTH / 2 - 1.5
  for (const side of [-1, 1]) {
    box(scene, [.1, 1.1, wallLength], [side * (FLOOR_HALF_WIDTH + 1.3), .55, wallMid], fence)
    for (let z = wallMid - wallLength / 2; z <= wallMid + wallLength / 2; z += 2.2) box(scene, [.12, 1.3, .12], [side * (FLOOR_HALF_WIDTH + 1.3), .65, z], fence)
  }
  box(scene, [FLOOR_HALF_WIDTH * 2 + 2.7, 1.1, .1], [0, .55, FIRST_ZONE_Z + FLOOR_DEPTH + 3.4], fence)

  // Torre de sonido, carpas, torres de luz y puerta de acceso.
  const fohZ = FIRST_ZONE_Z + FLOOR_DEPTH + .4
  box(scene, [5.2, .5, 3.4], [0, .25, fohZ], black)
  box(scene, [4.6, 1.1, 3], [0, 1.05, fohZ], std({ color: '#222a31', roughness: .8 }))
  box(scene, [4.2, .12, 1], [0, 1.7, fohZ - .6], std({ color: '#2f6bff', emissive: '#4d7dff', emissiveIntensity: 1.2 }))
  for (const side of [-1, 1]) {
    const x = side * 24
    box(scene, [7, .2, 6], [x, 3.1, 10], std({ color: side > 0 ? '#c9473b' : '#e6e1d6', roughness: .9 }))
    for (const dx of [-3.2, 3.2]) for (const dz of [-2.7, 2.7]) cylinder(scene, .08, .08, 3, [x + dx, 1.5, 10 + dz], metal, 8)
    box(scene, [5.2, 1, 1.4], [x, .5, 10.8], std({ color: '#2b343b', roughness: .7 }))
  }
  for (const [x, z] of [[-FLOOR_HALF_WIDTH - 3, 24], [FLOOR_HALF_WIDTH + 3, 24], [-FLOOR_HALF_WIDTH - 3, -4], [FLOOR_HALF_WIDTH + 3, -4]] as const) {
    cylinder(scene, .16, .22, 12, [x, 6, z], metal, 10, true)
    const head = box(scene, [2.2, 1, .3], [x, 12.3, z], std({ color: '#fff7dc', emissive: '#fff0bd', emissiveIntensity: 1.8 }))
    head.lookAt(0, 0, 8)
    if (!mobile) lightBeam(scene, new THREE.Vector3(x, 12, z), new THREE.Vector3(x * .5, 0, z * .5 + 6), '#fff2c8', 3.2, .035)
  }
  const gateZ = FIRST_ZONE_Z + FLOOR_DEPTH + 6.5
  for (const x of [-5, 5]) box(scene, [.5, 5, .5], [x, 2.5, gateZ], black)
  box(scene, [11, 1.1, .6], [0, 5.2, gateZ], std({ color: '#0f2a36', roughness: .6 }))

  // Zonas reales: profundidad proporcional al aforo, la de mayor precio junto al escenario.
  const ordered = [...zones].sort((a, b) => b.price - a.price)
  const totalCapacity = Math.max(1, ordered.reduce((sum, zone) => sum + zone.capacity, 0))
  const gap = 1
  const usable = FLOOR_DEPTH - gap * Math.max(0, ordered.length - 1)
  const placed = ordered.map((zone, index) => {
    const depth = Math.max(5, usable * zone.capacity / totalCapacity)
    const before = ordered.slice(0, index).reduce((sum, item) => sum + Math.max(5, usable * item.capacity / totalCapacity) + gap, 0)
    return { zone, depth, z: FIRST_ZONE_Z + before + depth / 2, hue: zoneHues[index % zoneHues.length] }
  })
  const slabs: Array<{ mesh: THREE.Mesh; zone: VenueZone; hue: string; outline: THREE.LineSegments; label: THREE.Sprite | null }> = []
  for (const item of placed) {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(FLOOR_HALF_WIDTH * 2 - .6, .12, item.depth), new THREE.MeshBasicMaterial({ color: item.hue, transparent: true, opacity: .5, depthWrite: false }))
    mesh.position.set(0, .12, item.z)
    mesh.userData.zoneId = item.zone.id
    scene.add(mesh)
    const outline = new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry), new THREE.LineBasicMaterial({ color: '#ffffff', transparent: true, opacity: .55 }))
    outline.position.copy(mesh.position)
    scene.add(outline)
    const label = labelSprite(`${item.zone.name} · S/ ${item.zone.price.toFixed(2)}`, { scale: 5.2, background: 'rgba(10,18,30,.86)' })
    if (label) { label.position.set(0, 3.4, item.z); scene.add(label) }
    slabs.push({ mesh, zone: item.zone, hue: item.hue, outline, label })
  }

  scene.add(new THREE.HemisphereLight('#7f7fc0', '#1d1830', 1.1))
  const moon = new THREE.DirectionalLight('#9fb4ff', .9)
  moon.position.set(-20, 40, 30)
  scene.add(moon)
  const stageWash = new THREE.PointLight('#ff6fb5', 600, 46, 2)
  stageWash.position.set(0, stageHeight + 9, STAGE_Z + 6)
  scene.add(stageWash)
  const crowdWash = new THREE.PointLight('#27e0c6', 380, 40, 2)
  crowdWash.position.set(0, 7, 6)
  scene.add(crowdWash)

  const updateSlab = (slab: typeof slabs[number], selectedZoneId: number | null) => {
    const material = slab.mesh.material as THREE.MeshBasicMaterial
    const selected = selectedZoneId === slab.zone.id
    const sold = slab.zone.available_capacity === 0
    material.color.set(sold ? '#7c8a91' : slab.hue)
    material.opacity = sold ? .3 : selected ? .85 : .5
    slab.mesh.position.y = selected ? .2 : .12
    slab.outline.position.y = slab.mesh.position.y
    ;(slab.outline.material as THREE.LineBasicMaterial).opacity = selected ? 1 : .55
  }

  return {
    views: [
      { id: 'general', label: 'Frente al escenario', position: new THREE.Vector3(0, 11, 34), target: new THREE.Vector3(0, 2.6, -7) },
      { id: 'zonas', label: 'Vista de zonas', position: new THREE.Vector3(0, 34, 30), target: new THREE.Vector3(0, 0, 6) },
      { id: 'escenario', label: 'Cerca del escenario', position: new THREE.Vector3(0, 3.2, 12), target: new THREE.Vector3(0, 6, -12) },
      { id: 'lateral', label: 'Lateral', position: new THREE.Vector3(40, 16, 6), target: new THREE.Vector3(0, 3, -2) },
    ],
    background: '#190f2e',
    minDistance: 8,
    maxDistance: 70,
    minPolar: .15,
    maxPolar: Math.PI / 2.05,
    pickables: slabs.map((slab) => slab.mesh),
    describe: (hit) => {
      const slab = slabs.find((item) => item.mesh === hit.object)
      if (!slab) return null
      return { text: `${slab.zone.name} · de pie · S/ ${slab.zone.price.toFixed(2)} · ${slab.zone.available_capacity} de ${slab.zone.capacity} disponibles`, enabled: slab.zone.available_capacity > 0, zoneId: slab.zone.id }
    },
    refresh: ({ selectedZoneId }) => slabs.forEach((slab) => updateSlab(slab, selectedZoneId)),
    legend: placed.map((item) => ({ label: `${item.zone.name} · S/ ${item.zone.price.toFixed(2)}`, color: item.hue })),
  }
}
