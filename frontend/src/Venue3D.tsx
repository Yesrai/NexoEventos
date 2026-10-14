import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { applyEnvironment } from './venue3d-kit'
import { buildConcert } from './venue3d-concert'
import { buildMuseum } from './venue3d-museum'
import { buildTheatre } from './venue3d-theatre'
import type { VenueBuild, VenueSeat, VenueZone } from './venue3d-types'

export type { VenueSeat, VenueZone }

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

function labelFor(kind: Props['kind']) {
  if (kind === 'theatre') return 'Visor tridimensional del Auditorio Nexo. Usa la lista de asientos como alternativa accesible.'
  if (kind === 'concert') return 'Visor tridimensional de Arena Parque Sur. Usa la lista de zonas como alternativa accesible.'
  return 'Recorrido tridimensional orientativo del museo.'
}

const NO_SEATS: VenueSeat[] = []
const NO_ZONES: VenueZone[] = []
const NO_SELECTION: number[] = []

const environmentIntensity = { theatre: .5, concert: .18, museum: .75 } as const

export default function Venue3D({ kind, seats = NO_SEATS, selectedSeatIds = NO_SELECTION, onToggleSeat, zones = NO_ZONES, selectedZoneId = null, onSelectZone, onUnavailable }: Props) {
  const hostRef = useRef<HTMLDivElement | null>(null)
  const stateRef = useRef({ selectedSeatIds, selectedZoneId })
  const handlersRef = useRef({ onToggleSeat, onSelectZone, onUnavailable })
  const buildRef = useRef<VenueBuild | null>(null)
  const renderRef = useRef<(() => void) | null>(null)
  const cameraApi = useRef<{ reset: () => void; zoom: (factor: number) => void; view: (id: string) => void } | null>(null)
  const [ready, setReady] = useState(false)
  const [hover, setHover] = useState<string | null>(null)
  const [views, setViews] = useState<Array<{ id: string; label: string }>>([])
  const [activeView, setActiveView] = useState<string | null>(null)
  const [legend, setLegend] = useState<VenueBuild['legend']>([])

  useEffect(() => { handlersRef.current = { onToggleSeat, onSelectZone, onUnavailable } }, [onToggleSeat, onSelectZone, onUnavailable])
  useEffect(() => {
    stateRef.current = { selectedSeatIds, selectedZoneId }
    buildRef.current?.refresh(stateRef.current)
    renderRef.current?.()
  }, [selectedSeatIds, selectedZoneId])

  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    let renderer: THREE.WebGLRenderer
    try { renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' }) } catch { handlersRef.current.onUnavailable(); return }
    const mobile = window.matchMedia('(max-width: 600px)').matches
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, mobile ? 1.25 : 1.75))
    renderer.setSize(host.clientWidth, host.clientHeight, false)
    renderer.outputColorSpace = THREE.SRGBColorSpace
    renderer.toneMapping = THREE.ACESFilmicToneMapping
    renderer.toneMappingExposure = kind === 'concert' ? 1.15 : 1.05
    renderer.shadowMap.enabled = !mobile && kind !== 'concert'
    renderer.shadowMap.type = THREE.PCFSoftShadowMap
    renderer.domElement.className = 'venue-3d-canvas'
    renderer.domElement.setAttribute('role', 'img')
    renderer.domElement.setAttribute('aria-label', labelFor(kind))
    renderer.domElement.tabIndex = 0
    host.appendChild(renderer.domElement)

    const buildStart = performance.now()
    const scene = new THREE.Scene()
    const environment = applyEnvironment(renderer, scene, environmentIntensity[kind])
    const build = kind === 'theatre' ? buildTheatre({ scene, renderer, mobile }, seats) : kind === 'concert' ? buildConcert({ scene, renderer, mobile }, zones) : buildMuseum({ scene, renderer, mobile })
    buildRef.current = build
    scene.background = scene.background ?? new THREE.Color(build.background)
    if (kind === 'theatre') scene.fog = new THREE.Fog(build.background, 30, 60)
    if (kind === 'museum') scene.fog = new THREE.Fog(build.background, 70, 130)

    // En pantallas verticales se aleja la cámara para que el recinto quepa a lo ancho.
    const fitPosition = (view: { position: THREE.Vector3; target: THREE.Vector3 }) => {
      const aspect = host.clientWidth / Math.max(1, host.clientHeight)
      if (aspect >= .9 || kind === 'theatre') return view.position.clone()
      const offset = view.position.clone().sub(view.target)
      return view.target.clone().add(offset.multiplyScalar(Math.min(1.5, Math.pow(1 / aspect, .6))))
    }
    const [firstView] = build.views
    const baseFov = kind === 'museum' ? 38 : kind === 'theatre' ? 52 : 44
    // En pantallas verticales se amplía el campo de visión para no recortar el recinto.
    const fitFov = (aspect: number) => aspect < 1 ? Math.min(78, baseFov * (1 + (1 - aspect) * 1.25)) : baseFov
    const camera = new THREE.PerspectiveCamera(fitFov(host.clientWidth / host.clientHeight), host.clientWidth / host.clientHeight, .1, 400)
    camera.position.copy(fitPosition(firstView))
    const controls = new OrbitControls(camera, renderer.domElement)
    controls.target.copy(firstView.target)
    controls.enablePan = false
    controls.minDistance = build.minDistance
    controls.maxDistance = build.maxDistance * (host.clientWidth < host.clientHeight ? 1.5 : 1)
    controls.minPolarAngle = build.minPolar
    controls.maxPolarAngle = build.maxPolar
    controls.update()

    const render = () => {
      if (build.bounds) camera.position.clamp(build.bounds.min, build.bounds.max)
      renderer.render(scene, camera)
    }
    renderRef.current = render
    controls.addEventListener('change', render)
    build.refresh(stateRef.current)
    render()
    if (import.meta.env.DEV) {
      // Solo en desarrollo: contadores reales para la evidencia de rendimiento (scripts/capture-venues.mjs).
      const { render: info, memory } = renderer.info
      ;(window as unknown as { __venue3dStats?: unknown }).__venue3dStats = { kind, buildMs: Math.round(performance.now() - buildStart), drawCalls: info.calls, triangles: info.triangles, geometries: memory.geometries, textures: memory.textures }
    }
    setViews(build.views.map(({ id, label }) => ({ id, label })))
    setActiveView(firstView.id)
    setLegend(build.legend)
    setReady(true)

    let frame = 0
    const goTo = (position: THREE.Vector3, target: THREE.Vector3) => {
      cancelAnimationFrame(frame)
      if (reducedMotion) { camera.position.copy(position); controls.target.copy(target); controls.update(); render(); return }
      const startPosition = camera.position.clone()
      const startTarget = controls.target.clone()
      const begin = performance.now()
      const step = (now: number) => {
        const progress = Math.min(1, (now - begin) / 700)
        const eased = progress < .5 ? 2 * progress * progress : 1 - Math.pow(-2 * progress + 2, 2) / 2
        camera.position.lerpVectors(startPosition, position, eased)
        controls.target.lerpVectors(startTarget, target, eased)
        controls.update()
        render()
        if (progress < 1) frame = requestAnimationFrame(step)
      }
      frame = requestAnimationFrame(step)
    }
    cameraApi.current = {
      reset: () => { setActiveView(firstView.id); goTo(fitPosition(firstView), firstView.target) },
      zoom: (factor) => {
        const offset = camera.position.clone().sub(controls.target)
        offset.setLength(Math.max(controls.minDistance, Math.min(controls.maxDistance, offset.length() * factor)))
        camera.position.copy(controls.target).add(offset)
        controls.update(); render()
      },
      view: (id) => { const view = build.views.find((item) => item.id === id); if (view) { setActiveView(id); goTo(fitPosition(view), view.target) } },
    }

    const raycaster = new THREE.Raycaster()
    const pointer = new THREE.Vector2()
    const hitAt = (event: PointerEvent) => {
      if (!build.pickables.length) return null
      const bounds = renderer.domElement.getBoundingClientRect()
      pointer.set((event.clientX - bounds.left) / bounds.width * 2 - 1, -((event.clientY - bounds.top) / bounds.height * 2 - 1))
      raycaster.setFromCamera(pointer, camera)
      const hit = raycaster.intersectObjects(build.pickables, false)[0]
      return hit ? build.describe(hit) : null
    }
    const onMove = (event: PointerEvent) => {
      const info = hitAt(event)
      setHover(info ? info.text : null)
      renderer.domElement.style.cursor = info ? (info.enabled ? 'pointer' : 'not-allowed') : 'grab'
    }
    let downAt: { x: number; y: number } | null = null
    const onDown = (event: PointerEvent) => { downAt = { x: event.clientX, y: event.clientY } }
    const onUp = (event: PointerEvent) => {
      // Un arrastre de cámara no debe seleccionar: se exige un toque casi estático.
      if (!downAt || Math.hypot(event.clientX - downAt.x, event.clientY - downAt.y) > 6) return
      const info = hitAt(event)
      if (!info || !info.enabled) return
      if (info.seat) handlersRef.current.onToggleSeat?.(info.seat)
      else if (info.zoneId !== undefined) handlersRef.current.onSelectZone?.(info.zoneId)
    }
    renderer.domElement.addEventListener('pointermove', onMove)
    renderer.domElement.addEventListener('pointerdown', onDown)
    renderer.domElement.addEventListener('pointerup', onUp)
    const observer = new ResizeObserver(() => {
      if (!host.clientWidth || !host.clientHeight) return
      camera.aspect = host.clientWidth / host.clientHeight
      camera.fov = fitFov(camera.aspect)
      camera.updateProjectionMatrix()
      renderer.setSize(host.clientWidth, host.clientHeight, false)
      render()
    })
    observer.observe(host)
    const onContextLost = (event: Event) => { event.preventDefault(); handlersRef.current.onUnavailable() }
    renderer.domElement.addEventListener('webglcontextlost', onContextLost)

    return () => {
      cancelAnimationFrame(frame)
      observer.disconnect()
      controls.removeEventListener('change', render)
      controls.dispose()
      renderer.domElement.removeEventListener('pointermove', onMove)
      renderer.domElement.removeEventListener('pointerdown', onDown)
      renderer.domElement.removeEventListener('pointerup', onUp)
      renderer.domElement.removeEventListener('webglcontextlost', onContextLost)
      const disposeMaterial = (material: THREE.Material) => {
        const textured = material as THREE.Material & { map?: THREE.Texture | null; emissiveMap?: THREE.Texture | null }
        textured.map?.dispose()
        textured.emissiveMap?.dispose()
        material.dispose()
      }
      scene.traverse((object) => {
        if (object instanceof THREE.Mesh || object instanceof THREE.Line || object instanceof THREE.Points) {
          object.geometry.dispose()
          const materials = Array.isArray(object.material) ? object.material : [object.material]
          materials.forEach(disposeMaterial)
        } else if (object instanceof THREE.Sprite) disposeMaterial(object.material)
      })
      environment.dispose()
      renderer.dispose()
      renderer.domElement.remove()
      renderRef.current = null
      buildRef.current = null
      cameraApi.current = null
    }
  }, [kind, seats, zones])

  return <div className={`venue-3d-shell venue-3d-${kind}`}>
    <div className="venue-3d-stage">
      <div className="venue-3d-toolbar" role="group" aria-label="Controles de cámara 3D"><button type="button" aria-label="Acercar cámara" onClick={() => cameraApi.current?.zoom(.8)}>+</button><button type="button" aria-label="Alejar cámara" onClick={() => cameraApi.current?.zoom(1.25)}>−</button><button type="button" onClick={() => cameraApi.current?.reset()}>Restablecer</button></div>
      <div ref={hostRef} className="venue-3d-host" aria-busy={!ready} />
      {!ready && <div className="venue-3d-loading" role="status"><span className="spinner" />Preparando ambiente 3D…</div>}
      {ready && views.length > 1 && <div className="venue-3d-views" role="group" aria-label="Vistas de cámara">{views.map((view) => <button type="button" key={view.id} className={activeView === view.id ? 'active' : ''} aria-pressed={activeView === view.id} onClick={() => cameraApi.current?.view(view.id)}>{view.label}</button>)}</div>}
      <div className="venue-3d-hint">Arrastra para girar · Rueda o pellizco para acercar</div>
      {hover && <div className="venue-3d-tooltip" role="status">{hover}</div>}
    </div>
    {legend.length > 0 && <ul className="venue-3d-legend" aria-label="Zonas del plano">{legend.map((item) => <li key={item.label}><i style={{ background: item.color }} />{item.label}</li>)}</ul>}
    <p className="venue-3d-note">{kind === 'museum' ? 'Recorrido orientativo de un museo ficticio. Las salas no se reservan: el acceso es por fecha, horario y cantidad.' : 'Representación 3D propia de un recinto ficticio. Solo el inventario real de esta función permite reservar.'}</p>
  </div>
}
