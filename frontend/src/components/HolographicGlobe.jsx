import { useRef, useMemo } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { Sphere, OrbitControls } from '@react-three/drei'
import * as THREE from 'three'

// 地球组件
function HolographicGlobe() {
  const globeRef = useRef()
  const pointsRef = useRef()
  
  // 生成数据点（模拟全球数据中心）
  const dataPoints = useMemo(() => {
    const points = []
    const pointCount = 100
    
    for (let i = 0; i < pointCount; i++) {
      // 球面坐标
      const phi = Math.acos(-1 + (2 * i) / pointCount)
      const theta = Math.sqrt(pointCount * Math.PI) * phi
      
      // 转换为 3D 坐标
      const radius = 2.05
      const x = radius * Math.cos(theta) * Math.sin(phi)
      const y = radius * Math.sin(theta) * Math.sin(phi)
      const z = radius * Math.cos(phi)
      
      points.push(x, y, z)
    }
    
    return new Float32Array(points)
  }, [])

  useFrame((state) => {
    if (globeRef.current) {
      globeRef.current.rotation.y = state.clock.elapsedTime * 0.1
    }
    if (pointsRef.current) {
      pointsRef.current.rotation.y = state.clock.elapsedTime * 0.1
    }
  })

  return (
    <group>
      {/* 主地球球体 */}
      <Sphere ref={globeRef} args={[2, 64, 64]}>
        <meshStandardMaterial
          color="#001a33"
          transparent
          opacity={0.3}
          wireframe={false}
        />
      </Sphere>

      {/* 线框地球 */}
      <Sphere args={[2.01, 32, 32]}>
        <meshBasicMaterial
          color="#00ff88"
          wireframe
          transparent
          opacity={0.2}
        />
      </Sphere>

      {/* 数据点 */}
      <points ref={pointsRef}>
        <bufferGeometry>
          <bufferAttribute
            attach="attributes-position"
            count={dataPoints.length / 3}
            array={dataPoints}
            itemSize={3}
          />
        </bufferGeometry>
        <pointsMaterial
          size={0.05}
          color="#00ff88"
          transparent
          opacity={0.8}
          sizeAttenuation
          blending={THREE.AdditiveBlending}
        />
      </points>

      {/* 外发光环 */}
      <mesh rotation={[Math.PI / 2, 0, 0]}>
        <ringGeometry args={[2.5, 2.6, 64]} />
        <meshBasicMaterial
          color="#00ff88"
          transparent
          opacity={0.3}
          side={THREE.DoubleSide}
          blending={THREE.AdditiveBlending}
        />
      </mesh>

      {/* 第二个光环 */}
      <mesh rotation={[Math.PI / 3, Math.PI / 4, 0]}>
        <ringGeometry args={[2.8, 2.9, 64]} />
        <meshBasicMaterial
          color="#00b4d8"
          transparent
          opacity={0.2}
          side={THREE.DoubleSide}
          blending={THREE.AdditiveBlending}
        />
      </mesh>
    </group>
  )
}

// 主场景
function Scene() {
  return (
    <>
      <ambientLight intensity={0.5} />
      <pointLight position={[10, 10, 10]} intensity={1} color="#00ff88" />
      <pointLight position={[-10, -10, -10]} intensity={0.5} color="#00b4d8" />
      <HolographicGlobe />
      <OrbitControls
        enableZoom={false}
        enablePan={false}
        autoRotate
        autoRotateSpeed={0.5}
      />
    </>
  )
}

// 导出的地球组件
export default function HolographicGlobeComponent() {
  return (
    <div style={{
      width: '100%',
      height: '100%',
      position: 'relative',
    }}>
      <Canvas
        camera={{ position: [0, 0, 6], fov: 50 }}
        style={{ background: 'transparent' }}
      >
        <Scene />
      </Canvas>
      
      {/* 全息效果覆盖层 */}
      <div style={{
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        pointerEvents: 'none',
        background: 'radial-gradient(circle at center, transparent 30%, rgba(0, 255, 136, 0.05) 70%)',
      }} />
    </div>
  )
}
