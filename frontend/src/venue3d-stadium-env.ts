import * as THREE from 'three'
import { box, concreteTexture, cylinder, seededRandom, skyGradient, std } from './venue3d-kit'

/* Entorno exterior del Estadio Nexo: es escenografía sin inventario vendible.
   Todo se genera de forma procedural; no se usan modelos ni texturas de terceros. */

function parkingTexture() {
  const canvas = document.createElement('canvas')
  canvas.width = 256
  canvas.height = 256
  const context = canvas.getContext('2d')
  if (context) {
    context.fillStyle = '#4a4f55'
    context.fillRect(0, 0, 256, 256)
    const random = seededRandom(5)
    for (let index = 0; index < 1800; index += 1) { context.fillStyle = `rgba(${random() > .5 ? '255,255,255' : '0,0,0'},${random() * .1})`; context.fillRect(random() * 256, random() * 256, 2, 2) }
    context.strokeStyle = 'rgba(240,240,240,.7)'
    context.lineWidth = 3
    for (let x = 0; x <= 256; x += 32) { context.beginPath(); context.moveTo(x, 20); context.lineTo(x, 120); context.stroke(); context.beginPath(); context.moveTo(x, 136); context.lineTo(x, 236); context.stroke() }
  }
  const texture = new THREE.CanvasTexture(context ? canvas : document.createElement('canvas'))
  texture.colorSpace = THREE.SRGBColorSpace
  texture.wrapS = THREE.RepeatWrapping
  texture.wrapT = THREE.RepeatWrapping
  texture.repeat.set(22, 22)
  return texture
}

function skylineTexture() {
  const canvas = document.createElement('canvas')
  canvas.width = 64
  canvas.height = 128
  const context = canvas.getContext('2d')
  if (context) {
    const random = seededRandom(31)
    context.fillStyle = '#9fb0bb'
    context.fillRect(0, 0, 64, 128)
    for (let y = 6; y < 124; y += 10) for (let x = 4; x < 60; x += 9) { context.fillStyle = random() > .4 ? '#c9d9e2' : '#7f93a1'; context.fillRect(x, y, 5, 6) }
  }
  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  return texture
}

export function addStadiumEnvironment(scene: THREE.Scene, mobile: boolean) {
  const random = seededRandom(90)
  const dome = new THREE.Mesh(new THREE.SphereGeometry(190, 24, 16), new THREE.MeshBasicMaterial({ map: skyGradient('#5fa5de', '#d9eaf4', '#e7eef1'), side: THREE.BackSide, fog: false }))
  scene.add(dome)

  // Playa de estacionamiento, avenida perimetral y accesos.
  const lot = new THREE.Mesh(new THREE.CircleGeometry(150, 48), new THREE.MeshStandardMaterial({ map: parkingTexture(), roughness: 1 }))
  lot.rotation.x = -Math.PI / 2
  lot.position.y = -1.3
  lot.receiveShadow = true
  scene.add(lot)
  const road = new THREE.Mesh(new THREE.RingGeometry(40, 48, 72), new THREE.MeshStandardMaterial({ color: '#30353a', roughness: .95, side: THREE.DoubleSide }))
  road.rotation.x = -Math.PI / 2
  road.position.y = -1.28
  scene.add(road)
  const plaza = new THREE.Mesh(new THREE.RingGeometry(29, 40, 72), new THREE.MeshStandardMaterial({ map: concreteTexture('#8d979b', [30, 3], 12), roughness: .95, side: THREE.DoubleSide }))
  plaza.rotation.x = -Math.PI / 2
  plaza.position.y = -1.27
  plaza.receiveShadow = true
  scene.add(plaza)

  // Fachada perimetral: zócalo, columnas y viga anular con cuatro portales de acceso.
  const concrete = std({ map: concreteTexture('#aeb7ba', [10, 1], 3), roughness: .9 })
  const columnCount = 56
  const columns = new THREE.InstancedMesh(new THREE.CylinderGeometry(.34, .4, 7.2, 10), concrete, columnCount)
  const dummy = new THREE.Object3D()
  let placed = 0
  for (let index = 0; index < columnCount; index += 1) {
    const angle = index / columnCount * Math.PI * 2
    if (Math.abs(Math.sin(angle * 2)) < .13) continue
    dummy.position.set(Math.cos(angle) * 36.5, 2.3, Math.sin(angle) * 36.5)
    dummy.updateMatrix()
    columns.setMatrixAt(placed, dummy.matrix)
    placed += 1
  }
  columns.count = placed
  columns.castShadow = !mobile
  scene.add(columns)
  const beam = new THREE.Mesh(new THREE.TorusGeometry(36.5, .5, 8, 96), std({ color: '#6c7a82', roughness: .6, metalness: .35 }))
  beam.rotation.x = Math.PI / 2
  beam.position.y = 5.9
  scene.add(beam)
  const band = new THREE.Mesh(new THREE.CylinderGeometry(36.6, 36.6, 1.4, 96, 1, true), new THREE.MeshStandardMaterial({ color: '#1f6f86', roughness: .4, metalness: .2, side: THREE.DoubleSide }))
  band.position.y = 5.1
  scene.add(band)
  for (const angle of [0, Math.PI / 2, Math.PI, Math.PI * 1.5]) {
    const x = Math.cos(angle) * 36.5
    const z = Math.sin(angle) * 36.5
    const gate = new THREE.Group()
    gate.position.set(x, 0, z)
    gate.rotation.y = -angle + Math.PI / 2
    box(gate, [.9, 8.2, .9], [-3.6, 2.8, 0], concrete, { cast: true })
    box(gate, [.9, 8.2, .9], [3.6, 2.8, 0], concrete, { cast: true })
    box(gate, [9.2, 1.4, 1.1], [0, 6.9, 0], std({ color: '#0f6179', roughness: .5 }))
    box(gate, [6.2, .12, .12], [0, 6.2, .5], std({ color: '#ffffff', emissive: '#e8fbff', emissiveIntensity: 1.4 }))
    scene.add(gate)
  }

  // Bloques de acceso y evacuación en las cuatro esquinas (sin asientos ni inventario).
  const stairs = std({ map: concreteTexture('#6f7a80', [3, 3], 22), roughness: .95 })
  for (const sx of [-1, 1]) for (const sz of [-1, 1]) {
    for (let level = 0; level < 3; level += 1) {
      const widthX = 12 - level * 2.6
      const depthZ = 8 - level * 1.8
      const height = .7 + level * .7
      box(scene, [widthX, height, depthZ], [sx * (17 + level * .4), height / 2 - .1, sz * (14.5 + level * .2)], stairs, { cast: true })
    }
    cylinder(scene, .08, .08, 1.2, [sx * 10.2, .6, sz * 9.4], std({ color: '#415661', metalness: .6, roughness: .4 }), 8)
  }

  // Vehículos, arbolado y horizonte urbano.
  const carCount = mobile ? 70 : 150
  const cars = new THREE.InstancedMesh(new THREE.BoxGeometry(3.7, 1.2, 1.7), new THREE.MeshStandardMaterial({ color: '#ffffff', roughness: .35, metalness: .5 }), carCount)
  const tints = ['#c9d2d8', '#2d3e4d', '#9a2f2f', '#e7e1d3', '#4d6a58', '#1d2228', '#b8742c']
  let car = 0
  for (let ring = 0; ring < 3 && car < carCount; ring += 1) {
    const radius = 56 + ring * 12
    const stalls = Math.floor(radius * Math.PI * 2 / 2.7)
    for (let stall = 0; stall < stalls && car < carCount; stall += 1) {
      if (random() < .42) continue
      const angle = stall / stalls * Math.PI * 2
      dummy.position.set(Math.cos(angle) * radius, -.7, Math.sin(angle) * radius)
      dummy.rotation.set(0, -angle, 0)
      dummy.updateMatrix()
      cars.setMatrixAt(car, dummy.matrix)
      cars.setColorAt(car, new THREE.Color(tints[Math.floor(random() * tints.length)]))
      car += 1
    }
  }
  cars.count = car
  scene.add(cars)
  const treeCount = mobile ? 40 : 90
  const crowns = new THREE.InstancedMesh(new THREE.IcosahedronGeometry(2.6, 0), std({ color: '#4f8a5b', roughness: 1 }), treeCount)
  const trunks = new THREE.InstancedMesh(new THREE.CylinderGeometry(.22, .3, 3, 6), std({ color: '#5a4630', roughness: 1 }), treeCount)
  dummy.rotation.set(0, 0, 0)
  for (let index = 0; index < treeCount; index += 1) {
    const angle = random() * Math.PI * 2
    const radius = 86 + random() * 36
    const scale = .8 + random() * .8
    dummy.scale.setScalar(scale)
    dummy.position.set(Math.cos(angle) * radius, 1.6 * scale + 1, Math.sin(angle) * radius)
    dummy.updateMatrix(); trunks.setMatrixAt(index, dummy.matrix)
    dummy.position.y = 4.4 * scale + 1
    dummy.updateMatrix(); crowns.setMatrixAt(index, dummy.matrix)
  }
  scene.add(trunks, crowns)
  const windows = skylineTexture()
  for (let index = 0; index < 22; index += 1) {
    const angle = index / 22 * Math.PI * 2 + random() * .1
    const height = 18 + random() * 34
    const tower = new THREE.Mesh(new THREE.BoxGeometry(10 + random() * 8, height, 10 + random() * 8), new THREE.MeshStandardMaterial({ map: windows, roughness: .9 }))
    tower.position.set(Math.cos(angle) * 160, height / 2 - 1.3, Math.sin(angle) * 160)
    scene.add(tower)
  }
}
