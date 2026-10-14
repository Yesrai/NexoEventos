import * as THREE from 'three'
import { artTexture, box, concreteTexture, cylinder, labelSprite, lightBeam, marbleTexture, plane, plasterTexture, screenTexture, std, woodTexture } from './venue3d-kit'
import type { VenueBuild, VenueContext } from './venue3d-types'

const HEIGHT = 5
const DOOR = 3.6
const X0 = -18
const X1 = 18
const Z0 = -12
const Z1 = 12
const LOBBY_Z = 6

type Normal = [number, number]

/** Muro axial con huecos de puerta. Si `inward` existe se dibuja solo hacia ese lado (corte visual). */
function wall(scene: THREE.Scene, from: [number, number], to: [number, number], gaps: Array<[number, number]>, material: THREE.Material, cap: THREE.Material, inward?: Normal) {
  const horizontal = from[1] === to[1]
  const start = horizontal ? from[0] : from[1]
  const end = horizontal ? to[0] : to[1]
  const fixed = horizontal ? from[1] : from[0]
  const cuts = [...gaps].sort((a, b) => a[0] - b[0])
  const pieces: Array<[number, number, boolean]> = []
  let cursor = start
  for (const [gapStart, gapEnd] of cuts) { if (gapStart > cursor) pieces.push([cursor, gapStart, false]); pieces.push([gapStart, gapEnd, true]); cursor = gapEnd }
  if (cursor < end) pieces.push([cursor, end, false])
  for (const [a, b, isGap] of pieces) {
    const size = b - a
    const mid = (a + b) / 2
    const at = (y: number): [number, number, number] => horizontal ? [mid, y, fixed] : [fixed, y, mid]
    const solidHeight = isGap ? HEIGHT - DOOR : HEIGHT
    const centerY = isGap ? DOOR + solidHeight / 2 : HEIGHT / 2
    if (inward) {
      const rotationY = inward[0] === 1 ? Math.PI / 2 : inward[0] === -1 ? -Math.PI / 2 : inward[1] === -1 ? Math.PI : 0
      plane(scene, size, solidHeight, at(centerY), [0, rotationY, 0], material)
    } else {
      const wallBox = new THREE.Mesh(new THREE.BoxGeometry(horizontal ? size : .34, solidHeight, horizontal ? .34 : size), material)
      wallBox.position.set(...at(centerY))
      wallBox.castShadow = true
      wallBox.receiveShadow = true
      scene.add(wallBox)
    }
    if (!isGap) {
      const capMesh = new THREE.Mesh(new THREE.BoxGeometry(horizontal ? size : .4, .14, horizontal ? .4 : size), cap)
      capMesh.position.set(...at(HEIGHT + .06))
      scene.add(capMesh)
    }
  }
}

function pedestal(scene: THREE.Scene, x: number, z: number, stone: THREE.Material, height = .95) {
  box(scene, [1.5, height, 1.5], [x, height / 2, z], stone, { cast: true })
  box(scene, [1.65, .08, 1.65], [x, height + .04, z], std({ color: '#2a2c30', roughness: .4, metalness: .2 }))
  return height + .08
}

function bench(scene: THREE.Scene, x: number, z: number, along: 'x' | 'z', wood: THREE.Material, metal: THREE.Material) {
  const [w, d] = along === 'x' ? [2.6, .7] : [.7, 2.6]
  box(scene, [w, .1, d], [x, .5, z], wood, { cast: true })
  for (const offset of [-1, 1]) box(scene, along === 'x' ? [.1, .5, d - .1] : [w - .1, .5, .1], along === 'x' ? [x + offset * (w / 2 - .25), .25, z] : [x, .25, z + offset * (d / 2 - .25)], metal)
}

export function buildMuseum({ scene, mobile }: VenueContext): VenueBuild {
  const plaster = std({ map: plasterTexture('#f1eee7', [8, 2]), roughness: .95 })
  const accent = std({ map: plasterTexture('#d9dfe0', [8, 2], 14), roughness: .95 })
  const cap = std({ color: '#2b3a43', roughness: .6 })
  const stone = std({ map: concreteTexture('#c6bfb2', [1, 1], 33), roughness: .9 })
  const dark = std({ color: '#262a2e', roughness: .5, metalness: .4 })
  const brass = std({ color: '#c8a45a', roughness: .3, metalness: .9 })
  const woodMaterial = std({ map: woodTexture('#b98d5a', [1, 1], 6), roughness: .55 })
  const light = std({ color: '#ffffff', emissive: '#fff4de', emissiveIntensity: 1.6 })
  const ceiling = std({ color: '#f4f1ea', roughness: 1 })
  const glass = new THREE.MeshPhysicalMaterial({ color: '#b6dcea', transparent: true, opacity: .22, roughness: .05, metalness: .1, transmission: 0, depthWrite: false })

  // Base exterior y suelos diferenciados por sala.
  plane(scene, 90, 70, [0, -.42, 0], [-Math.PI / 2, 0, 0], std({ map: concreteTexture('#b8bec0', [14, 12], 8), roughness: 1 }))
  box(scene, [X1 - X0 + 1.2, .4, Z1 - Z0 + 1.2], [0, -.2, 0], std({ color: '#a39d92', roughness: .95 }))
  plane(scene, 36, 6, [0, .003, (LOBBY_Z + Z1) / 2], [-Math.PI / 2, 0, 0], std({ map: marbleTexture([9, 1.5]), roughness: .18, metalness: .08 }))
  plane(scene, 12, 18, [-12, .003, (Z0 + LOBBY_Z) / 2], [-Math.PI / 2, 0, 0], std({ map: woodTexture('#a67b4b', [6, 9], 5), roughness: .5, metalness: .03 }))
  plane(scene, 12, 18, [0, .003, (Z0 + LOBBY_Z) / 2], [-Math.PI / 2, 0, 0], std({ map: concreteTexture('#575b60', [6, 9], 41), roughness: .32, metalness: .2 }))
  plane(scene, 12, 18, [12, .003, (Z0 + LOBBY_Z) / 2], [-Math.PI / 2, 0, 0], std({ map: marbleTexture([6, 9], 77), roughness: .22, metalness: .05 }))

  // Muros perimetrales (solo cara interior) y particiones con vanos.
  wall(scene, [X0, Z1], [X1, Z1], [[-2, 2]], plaster, cap, [0, -1])
  wall(scene, [X0, Z0], [X1, Z0], [], accent, cap, [0, 1])
  wall(scene, [X0, Z0], [X0, Z1], [], plaster, cap, [1, 0])
  wall(scene, [X1, Z0], [X1, Z1], [[-4.8, -1.2]], plaster, cap, [-1, 0])
  wall(scene, [X0, LOBBY_Z], [X1, LOBBY_Z], [[-13.8, -10.2]], accent, cap)
  wall(scene, [-6, Z0], [-6, LOBBY_Z], [[-4.8, -1.2]], plaster, cap)
  wall(scene, [6, Z0], [6, LOBBY_Z], [[-4.8, -1.2]], plaster, cap)

  // Techos con claraboyas luminosas (cara inferior solamente: visibles desde dentro).
  for (const [cx, cz, w, d] of [[0, (LOBBY_Z + Z1) / 2, 36, 6], [-12, (Z0 + LOBBY_Z) / 2, 12, 18], [0, (Z0 + LOBBY_Z) / 2, 12, 18], [12, (Z0 + LOBBY_Z) / 2, 12, 18]] as const) {
    plane(scene, w, d, [cx, HEIGHT, cz], [Math.PI / 2, 0, 0], ceiling)
    for (let index = -1; index <= 1; index += 1) {
      if (d > 8) plane(scene, w - 4, 1.2, [cx, HEIGHT - .01, cz + index * 5], [Math.PI / 2, 0, 0], light)
      else plane(scene, 6, 1.4, [cx + index * 10, HEIGHT - .01, cz], [Math.PI / 2, 0, 0], light)
    }
  }

  // Recepción y vestíbulo.
  box(scene, [6, 1.1, 1.4], [8, .55, 9.2], std({ color: '#1f4e5f', roughness: .5 }), { cast: true })
  box(scene, [6.2, .08, 1.6], [8, 1.14, 9.2], stone)
  for (const x of [-1.9, 1.9]) box(scene, [1.8, DOOR, .08], [x, DOOR / 2, Z1 - .02], glass)
  for (const x of [-16, 16]) { cylinder(scene, .38, .3, .6, [x, .3, 9.5], std({ color: '#ddd7cb', roughness: .7 }), 16); for (let leaf = 0; leaf < 5; leaf += 1) cylinder(scene, .06, .02, 1.4 + leaf * .12, [x + (leaf - 2) * .17, 1.2 + leaf * .08, 9.5], std({ color: '#2f6d44', roughness: .9 }), 6) }
  bench(scene, -6, 9.4, 'x', woodMaterial, dark)

  // Sala 1: pintura mural y bancos.
  const artTextures = [0, 1, 2, 3, 4].map(artTexture)
  const artworks: Array<[number, number, number, number, number]> = [[-17.82, -9, 0, 1, 0], [-17.82, -3.2, 0, 1, 1], [-17.82, 2.6, 0, 1, 2], [-14, -11.82, 0, 0, 3], [-9, -11.82, 0, 0, 4]]
  artworks.forEach(([x, z, , facing, index]) => {
    const frame = new THREE.Group()
    frame.position.set(x, 2.5, z)
    frame.rotation.y = facing === 1 ? Math.PI / 2 : 0
    box(frame, [3.4, 2.4, .12], [0, 0, 0], dark)
    const canvasArt = new THREE.Mesh(new THREE.PlaneGeometry(3, 2), new THREE.MeshStandardMaterial({ map: artTextures[index % 5], roughness: .7 }))
    canvasArt.position.z = .07
    frame.add(canvasArt)
    scene.add(frame)
    const spot = new THREE.Vector3(x + (facing === 1 ? 1.2 : 0), 4.9, z + (facing === 1 ? 0 : 1.2))
    box(scene, [.2, .12, .2], [spot.x, spot.y, spot.z], light)
    if (!mobile) lightBeam(scene, spot, new THREE.Vector3(x + (facing === 1 ? .2 : 0), 1.6, z + (facing === 1 ? 0 : .2)), '#fff1d0', .9, .05)
  })
  bench(scene, -12, -4, 'z', woodMaterial, dark)
  bench(scene, -12, 1.5, 'x', woodMaterial, dark)
  box(scene, [4, 3, .14], [-8.2, 1.5, -7.2], accent, { cast: true })
  const centerPanel = new THREE.Mesh(new THREE.PlaneGeometry(3.4, 2.4), new THREE.MeshStandardMaterial({ map: artTextures[2], roughness: .7 }))
  centerPanel.position.set(-8.2, 1.7, -7.12)
  scene.add(centerPanel)

  // Sala 2: esculturas en pedestales, vitrinas y cordones.
  const sculptureMaterial = [std({ color: '#b36d48', roughness: .35, metalness: .45 }), std({ color: '#3c7b78', roughness: .3, metalness: .5 }), std({ color: '#d9d3c7', roughness: .4, metalness: .1 }), std({ color: '#7d6aa6', roughness: .35, metalness: .4 })]
  const sculptures: Array<[number, number, THREE.BufferGeometry, number]> = [
    [-3.6, -8.6, new THREE.TorusKnotGeometry(.46, .15, 72, 10), 0], [3.6, -8.6, new THREE.IcosahedronGeometry(.55, 1), 1],
    [-3.6, 2.4, new THREE.SphereGeometry(.5, 24, 16), 2], [3.6, 2.4, new THREE.OctahedronGeometry(.6, 0), 3],
  ]
  for (const [x, z, geometry, index] of sculptures) {
    const top = pedestal(scene, x, z, stone)
    const piece = new THREE.Mesh(geometry, sculptureMaterial[index])
    piece.position.set(x, top + .65, z); piece.castShadow = true
    scene.add(piece)
    if (!mobile) lightBeam(scene, new THREE.Vector3(x, 4.9, z), new THREE.Vector3(x, top + .2, z), '#fff1d0', .8, .06)
  }
  const centerTop = pedestal(scene, 0, -3.8, stone, .6)
  const showpiece = new THREE.Mesh(new THREE.TorusKnotGeometry(.7, .2, 96, 12, 2, 3), std({ color: '#e1b04a', roughness: .22, metalness: .9 }))
  showpiece.position.set(0, centerTop + 1.05, -3.8); showpiece.castShadow = true
  scene.add(showpiece)
  for (const [dx, dz] of [[-1.3, -1.3], [1.3, -1.3], [-1.3, 1.3], [1.3, 1.3]] as const) { cylinder(scene, .035, .035, .85, [dx, .43, -3.8 + dz], brass, 8); cylinder(scene, .12, .14, .04, [dx, .02, -3.8 + dz], brass, 12) }
  box(scene, [2.6, .035, .035], [0, .78, -5.1], std({ color: '#7a1c2c', roughness: .9 }))
  box(scene, [2.6, .035, .035], [0, .78, -2.5], std({ color: '#7a1c2c', roughness: .9 }))
  for (const x of [-2.6, 2.6]) {
    box(scene, [1.2, .9, 1.2], [x, .45, -.4], dark)
    box(scene, [1.1, 1.1, 1.1], [x, 1.45, -.4], glass)
    const relic = new THREE.Mesh(new THREE.CylinderGeometry(.18, .26, .55, 16), std({ color: '#a24c36', roughness: .5 }))
    relic.position.set(x, 1.15, -.4)
    scene.add(relic)
  }

  // Sala 3: instalación suspendida, pantalla de proyección y pufs.
  const orbMaterial = [std({ color: '#d1523f', roughness: .3 }), std({ color: '#2f9e8a', roughness: .3 }), std({ color: '#e6b84a', roughness: .3 })]
  for (let index = 0; index < 14; index += 1) {
    const angle = index * 2.4
    const x = 12 + Math.cos(angle) * (1 + index * .16)
    const z = 1.2 + Math.sin(angle) * (1 + index * .16)
    const y = 1.6 + (index % 5) * .55
    const orb = new THREE.Mesh(new THREE.SphereGeometry(.22 + (index % 3) * .1, 18, 12), orbMaterial[index % 3])
    orb.position.set(x, y, z)
    scene.add(orb)
    cylinder(scene, .006, .006, HEIGHT - y, [x, y + (HEIGHT - y) / 2, z], dark, 4)
  }
  const projection = screenTexture('ARTE', 'Sala 3')
  const screen = new THREE.Mesh(new THREE.PlaneGeometry(8, 3.6), new THREE.MeshStandardMaterial({ map: projection, emissive: '#ffffff', emissiveMap: projection, emissiveIntensity: .9 }))
  screen.position.set(12, 2.7, Z0 + .14)
  scene.add(screen)
  for (const [x, z] of [[9.2, -8], [10.6, -8.8], [14.8, -8.2]] as const) cylinder(scene, .45, .45, .4, [x, .2, z], std({ color: '#2f6b80', roughness: .95 }), 18)

  // Recorrido recomendado sobre el piso, con chevrones direccionales.
  const route: Array<[number, number]> = [[0, 11], [-12, 9], [-12, LOBBY_Z], [-12, -3], [-6, -3], [6, -3], [17.2, -3]]
  const routeMaterial = std({ color: '#00c2a5', emissive: '#00e0bd', emissiveIntensity: .9, roughness: .5 })
  for (let index = 0; index < route.length - 1; index += 1) {
    const [ax, az] = route[index]
    const [bx, bz] = route[index + 1]
    const lengthSegment = Math.hypot(bx - ax, bz - az)
    const strip = box(scene, [lengthSegment, .02, .22], [(ax + bx) / 2, .03, (az + bz) / 2], routeMaterial, { receive: false })
    strip.rotation.y = -Math.atan2(bz - az, bx - ax)
    for (let at = 1.5; at < lengthSegment - .8; at += 3) {
      const chevron = new THREE.Mesh(new THREE.ConeGeometry(.36, .6, 3), routeMaterial)
      chevron.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), new THREE.Vector3(bx - ax, 0, bz - az).normalize())
      chevron.position.set(ax + (bx - ax) * at / lengthSegment, .06, az + (bz - az) * at / lengthSegment)
      scene.add(chevron)
    }
  }
  const labels: Array<[string, number, number, number]> = [['Ingreso', 0, 3.7, 9], ['Sala 1', -12, 4.1, -2], ['Sala 2', 0, 4.1, -9.5], ['Sala 3', 12, 4.1, -9.5], ['Salida', 16.4, 3.6, -3]]
  for (const [text, x, y, z] of labels) {
    const tag = labelSprite(text, { scale: 4.2, background: text === 'Ingreso' || text === 'Salida' ? 'rgba(0,150,128,.95)' : 'rgba(22,49,63,.9)' })
    if (tag) { tag.position.set(x, y, z); scene.add(tag) }
  }

  scene.add(new THREE.HemisphereLight('#ffffff', '#cfc6b8', 1.7))
  const sun = new THREE.DirectionalLight('#fff4e0', 2.4)
  sun.position.set(-14, 30, 18)
  sun.castShadow = !mobile
  sun.shadow.mapSize.set(2048, 2048)
  sun.shadow.camera.left = -26; sun.shadow.camera.right = 26; sun.shadow.camera.top = 20; sun.shadow.camera.bottom = -20
  sun.shadow.camera.far = 90
  sun.shadow.bias = -.0004
  scene.add(sun)
  if (!mobile) for (const [x, z] of [[-12, -3], [0, -3], [12, -3], [0, 9]] as const) {
    const point = new THREE.PointLight('#fff1d6', 40, 16, 2)
    point.position.set(x, HEIGHT - .8, z)
    scene.add(point)
  }

  return {
    views: [
      { id: 'general', label: 'Vista general', position: new THREE.Vector3(2, 32, 34), target: new THREE.Vector3(0, 0, 0) },
      { id: 'ingreso', label: 'Ingreso', position: new THREE.Vector3(0, 3.4, 15), target: new THREE.Vector3(-6, 1.5, 2) },
      { id: 'sala1', label: 'Sala 1', position: new THREE.Vector3(-12, 3.2, 3), target: new THREE.Vector3(-14, 2, -8) },
      { id: 'sala2', label: 'Sala 2', position: new THREE.Vector3(0, 3.2, 3.5), target: new THREE.Vector3(0, 1.3, -6) },
      { id: 'sala3', label: 'Sala 3', position: new THREE.Vector3(12, 3.2, 3), target: new THREE.Vector3(12, 1.8, -7) },
    ],
    background: '#dfe3e2',
    minDistance: 5,
    maxDistance: 62,
    minPolar: .2,
    maxPolar: Math.PI / 2.05,
    pickables: [],
    describe: () => null,
    refresh: () => undefined,
    legend: [],
  }
}
