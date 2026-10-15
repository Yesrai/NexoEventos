import type * as THREE from 'three'

export type VenueSeat = { id: number; zone_id: number; zone_name: string; row: string; number: number; price: number; available: boolean }
export type VenueZone = { id: number; name: string; price: number; capacity: number; available_capacity: number }

export type VenueView = { id: string; label: string; position: THREE.Vector3; target: THREE.Vector3 }

export type VenueContext = { scene: THREE.Scene; renderer: THREE.WebGLRenderer; mobile: boolean }

export type VenueBuild = {
  views: VenueView[]
  background: string
  minDistance: number
  maxDistance: number
  minPolar: number
  maxPolar: number
  /** Limita la cámara a este volumen (p. ej. dentro de una sala). */
  bounds?: THREE.Box3
  /** Objetos con los que el puntero puede interactuar y su descripción. */
  pickables: THREE.Object3D[]
  describe: (hit: THREE.Intersection) => { text: string; enabled: boolean; seat?: VenueSeat; zoneId?: number } | null
  /** Repinta colores según selección. */
  refresh: (state: { selectedSeatIds: number[]; selectedZoneId: number | null }) => void
  legend: Array<{ label: string; color: string }>
}

export const zonePalette = ['#c9892b', '#4f8a6a', '#7a5aa6', '#b5523f']

/** Color estable por rango de precio ascendente para que la leyenda coincida con la escena. */
export function zoneColors(items: Array<{ id: number; price: number }>) {
  const unique = [...new Map(items.map((item) => [item.id, item.price])).entries()].sort((a, b) => a[1] - b[1])
  return new Map(unique.map(([id], index) => [id, zonePalette[index % zonePalette.length]]))
}
