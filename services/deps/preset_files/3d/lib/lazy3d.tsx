import { lazy, Suspense } from 'react';

/**
 * Lazy 3D wrapper (Dependency Management Plan, P3).
 *
 * Renders 3D content through these so `three` / `@react-three/fiber` /
 * `@react-three/drei` are code-split into separate chunks by Vite and are
 * NOT downloaded until a 3D scene actually mounts. Standard pages never
 * pay for 3D.
 *
 * Usage:
 *   import { LazyCanvas, loadThree } from '@/lib/lazy3d';
 *
 *   function Scene() {
 *     const three = use(loadThree()); // or loadThree().then(m => ...)
 *     return (
 *       <Suspense fallback={null}>
 *         <LazyCanvas camera={{ position: [0, 0, 5] }}>
 *           <mesh>
 *             <boxGeometry args={[1, 1, 1]} />
 *             <meshStandardMaterial color="orange" />
 *           </mesh>
 *         </LazyCanvas>
 *       </Suspense>
 *     );
 *   }
 *
 * Import drei helpers INSIDE the Canvas children (they resolve after the
 * 3D chunk loads):
 *   const { OrbitControls } = await import('@react-three/drei');
 */

// Canvas as a lazy component — the fiber chunk loads on first mount.
export const LazyCanvas = lazy(() =>
  import('@react-three/fiber').then((m) => ({ default: m.Canvas })));

// three itself is a module (not a component) — expose a promise loader.
export const loadThree = () => import('three');

// Convenience: lazy drei helpers via a named-export wrapper.
// e.g. const LazyOrbitControls = lazyDrei('OrbitControls')
export function lazyDrei<T extends keyof typeof import('@react-three/drei')>(
  name: T,
) {
  return lazy(() =>
    import('@react-three/drei').then((m) => ({ default: m[name] as never })));
}
