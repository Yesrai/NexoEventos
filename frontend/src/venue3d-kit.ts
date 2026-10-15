import * as THREE from 'three'
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js'

/* Utilidades compartidas por los ambientes 3D. Todas las texturas se generan
   proceduralmente en canvas: no hay recursos externos ni licencias de terceros. */

export function seededRandom(seed: number) {
  let state = seed >>> 0
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0
    return state / 4294967296
  }
}

function canvasTexture(size: number, draw: (context: CanvasRenderingContext2D, size: number) => void, repeat: [number, number] = [1, 1]) {
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const context = canvas.getContext('2d')
  if (!context) return null
  draw(context, size)
  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  texture.wrapS = THREE.RepeatWrapping
  texture.wrapT = THREE.RepeatWrapping
  texture.repeat.set(...repeat)
  texture.anisotropy = 4
  return texture
}

function speckle(context: CanvasRenderingContext2D, size: number, count: number, alpha: number, random: () => number) {
  for (let index = 0; index < count; index += 1) {
    const tone = random() > .5 ? 255 : 0
    context.fillStyle = `rgba(${tone},${tone},${tone},${random() * alpha})`
    context.fillRect(random() * size, random() * size, 1 + random() * 2, 1 + random() * 2)
  }
}

export function woodTexture(base: string, repeat: [number, number], seed = 3) {
  return canvasTexture(512, (context, size) => {
    const random = seededRandom(seed)
    context.fillStyle = base
    context.fillRect(0, 0, size, size)
    const plank = size / 8
    for (let row = 0; row < 8; row += 1) {
      context.fillStyle = `rgba(${random() > .5 ? '255,235,200' : '30,15,5'},${.05 + random() * .13})`
      context.fillRect(0, row * plank, size, plank)
      context.fillStyle = 'rgba(20,10,5,.5)'
      context.fillRect(0, row * plank, size, 1.5)
      const offset = random() * size
      context.fillRect(offset, row * plank, 1.5, plank)
      context.strokeStyle = 'rgba(30,15,5,.08)'
      for (let grain = 0; grain < 5; grain += 1) {
        const y = row * plank + random() * plank
        context.beginPath()
        context.moveTo(0, y)
        context.bezierCurveTo(size * .3, y + random() * 4 - 2, size * .6, y + random() * 4 - 2, size, y)
        context.stroke()
      }
    }
  }, repeat)
}

export function carpetTexture(base: string, repeat: [number, number], seed = 5) {
  return canvasTexture(256, (context, size) => {
    context.fillStyle = base
    context.fillRect(0, 0, size, size)
    speckle(context, size, 5200, .22, seededRandom(seed))
  }, repeat)
}

export function concreteTexture(base: string, repeat: [number, number], seed = 7) {
  return canvasTexture(256, (context, size) => {
    const random = seededRandom(seed)
    context.fillStyle = base
    context.fillRect(0, 0, size, size)
    speckle(context, size, 2600, .18, random)
    context.strokeStyle = 'rgba(0,0,0,.07)'
    context.strokeRect(0, 0, size, size)
  }, repeat)
}

export function plasterTexture(base: string, repeat: [number, number], seed = 11) {
  return canvasTexture(256, (context, size) => {
    context.fillStyle = base
    context.fillRect(0, 0, size, size)
    speckle(context, size, 1800, .07, seededRandom(seed))
  }, repeat)
}

export function marbleTexture(repeat: [number, number], seed = 13) {
  return canvasTexture(512, (context, size) => {
    const random = seededRandom(seed)
    context.fillStyle = '#d9d5cd'
    context.fillRect(0, 0, size, size)
    context.strokeStyle = 'rgba(80,80,85,.10)'
    for (let vein = 0; vein < 14; vein += 1) {
      context.beginPath()
      let x = random() * size
      let y = 0
      context.moveTo(x, y)
      while (y < size) { x += random() * 36 - 18; y += 22 + random() * 24; context.lineTo(x, y) }
      context.stroke()
    }
    context.strokeStyle = 'rgba(0,0,0,.16)'
    context.strokeRect(0, 0, size, size)
    context.strokeRect(size / 2, 0, 0, size)
    context.strokeRect(0, size / 2, size, 0)
  }, repeat)
}

export function artTexture(index: number) {
  return canvasTexture(256, (context, size) => {
    const random = seededRandom(100 + index * 17)
    const palettes = [['#1f4e5f', '#e8c170', '#c4553d'], ['#2b2d42', '#ef8354', '#bfc0c0'], ['#3d5a80', '#98c1d9', '#ee6c4d'], ['#264653', '#2a9d8f', '#e9c46a'], ['#5f0f40', '#fb8b24', '#e36414']]
    const palette = palettes[index % palettes.length]
    context.fillStyle = palette[0]
    context.fillRect(0, 0, size, size)
    for (let shape = 0; shape < 6; shape += 1) {
      context.fillStyle = palette[1 + (shape % 2)]
      context.globalAlpha = .55 + random() * .4
      context.beginPath()
      if (shape % 3 === 0) context.arc(random() * size, random() * size, 24 + random() * 60, 0, Math.PI * 2)
      else context.rect(random() * size * .7, random() * size * .7, 40 + random() * 100, 30 + random() * 90)
      context.fill()
    }
    context.globalAlpha = 1
  })
}

export function screenTexture(title: string, subtitle: string) {
  return canvasTexture(512, (context, size) => {
    const gradient = context.createLinearGradient(0, 0, size, size)
    gradient.addColorStop(0, '#0b1f2d')
    gradient.addColorStop(.55, '#12475a')
    gradient.addColorStop(1, '#6a1f5c')
    context.fillStyle = gradient
    context.fillRect(0, 0, size, size)
    context.strokeStyle = 'rgba(0,194,165,.35)'
    for (let line = 0; line < 12; line += 1) {
      context.beginPath()
      context.arc(size * .7, size * .2, 40 + line * 36, 0, Math.PI * 2)
      context.stroke()
    }
    context.fillStyle = '#2f6bff'
    context.fillRect(56, 150, 10, 200)
    context.fillStyle = '#f7fbfc'
    context.font = '700 92px Arial'
    context.fillText(title, 90, 250)
    context.font = '400 38px Arial'
    context.fillText(subtitle, 92, 312)
  })
}

export function labelSprite(text: string, options: { scale?: number; color?: string; background?: string; badge?: boolean } = {}) {
  const canvas = document.createElement('canvas')
  const badge = Boolean(options.badge)
  canvas.width = badge ? 128 : 512
  canvas.height = badge ? 128 : 128
  const context = canvas.getContext('2d')
  if (!context) return null
  context.fillStyle = options.background ?? 'rgba(16,40,54,.82)'
  context.beginPath()
  if (badge) context.arc(64, 64, 56, 0, Math.PI * 2)
  else context.roundRect(6, 14, 500, 100, 28)
  context.fill()
  context.fillStyle = options.color ?? '#ffffff'
  context.font = badge ? '700 64px Arial' : '600 46px Arial'
  context.textAlign = 'center'
  context.textBaseline = 'middle'
  context.fillText(text, badge ? 64 : 256, badge ? 68 : 66)
  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthWrite: false }))
  const scale = options.scale ?? 4
  sprite.scale.set(scale, badge ? scale : scale / 4, 1)
  return sprite
}

export type Std = { color?: THREE.ColorRepresentation; map?: THREE.Texture | null; roughness?: number; metalness?: number; emissive?: THREE.ColorRepresentation; emissiveIntensity?: number; side?: THREE.Side }

export function std(options: Std) {
  return new THREE.MeshStandardMaterial({ roughness: .8, metalness: .02, ...options, map: options.map ?? null })
}

export function box(parent: THREE.Object3D, size: [number, number, number], position: [number, number, number], material: THREE.Material, flags: { cast?: boolean; receive?: boolean } = {}) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), material)
  mesh.position.set(...position)
  mesh.castShadow = Boolean(flags.cast)
  mesh.receiveShadow = flags.receive ?? true
  parent.add(mesh)
  return mesh
}

export function cylinder(parent: THREE.Object3D, radiusTop: number, radiusBottom: number, height: number, position: [number, number, number], material: THREE.Material, segments = 20, cast = false) {
  const mesh = new THREE.Mesh(new THREE.CylinderGeometry(radiusTop, radiusBottom, height, segments), material)
  mesh.position.set(...position)
  mesh.castShadow = cast
  mesh.receiveShadow = true
  parent.add(mesh)
  return mesh
}

/** Plano cuya cara visible mira hacia `normal`; por culling de caras, desde atrás es invisible (efecto corte arquitectónico). */
export function plane(parent: THREE.Object3D, width: number, height: number, position: [number, number, number], rotation: [number, number, number], material: THREE.Material) {
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(width, height), material)
  mesh.position.set(...position)
  mesh.rotation.set(...rotation)
  mesh.receiveShadow = true
  parent.add(mesh)
  return mesh
}

/** Cono de luz volumétrico falso: aditivo, sin escritura de profundidad, barato en GPU. */
export function lightBeam(parent: THREE.Object3D, from: THREE.Vector3, to: THREE.Vector3, color: THREE.ColorRepresentation, radius: number, opacity = .16) {
  const direction = to.clone().sub(from)
  const length = direction.length()
  const geometry = new THREE.CylinderGeometry(.04, radius, length, 18, 1, true)
  geometry.translate(0, -length / 2, 0)
  const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ color, transparent: true, opacity, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide }))
  mesh.position.copy(from)
  mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, -1, 0), direction.normalize())
  parent.add(mesh)
  return mesh
}

export function applyEnvironment(renderer: THREE.WebGLRenderer, scene: THREE.Scene, intensity: number) {
  const generator = new THREE.PMREMGenerator(renderer)
  const room = new RoomEnvironment()
  const target = generator.fromScene(room, .04)
  scene.environment = target.texture
  scene.environmentIntensity = intensity
  room.dispose()
  generator.dispose()
  return target
}

export function skyGradient(top: string, horizon: string, bottom: string) {
  return canvasTexture(256, (context, size) => {
    const gradient = context.createLinearGradient(0, 0, 0, size)
    gradient.addColorStop(0, top)
    gradient.addColorStop(.55, horizon)
    gradient.addColorStop(1, bottom)
    context.fillStyle = gradient
    context.fillRect(0, 0, size, size)
  })
}
