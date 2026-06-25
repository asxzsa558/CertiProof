import { useRef, useMemo } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import * as THREE from 'three'

// 粒子系统组件
function ParticleField() {
  const points = useRef()
  const particleCount = 2000

  const particles = useMemo(() => {
    const positions = new Float32Array(particleCount * 3)
    const colors = new Float32Array(particleCount * 3)
    
    for (let i = 0; i < particleCount; i++) {
      // 随机分布在球形空间
      const radius = 15 + Math.random() * 10
      const theta = Math.random() * Math.PI * 2
      const phi = Math.random() * Math.PI
      
      positions[i * 3] = radius * Math.sin(phi) * Math.cos(theta)
      positions[i * 3 + 1] = radius * Math.sin(phi) * Math.sin(theta)
      positions[i * 3 + 2] = radius * Math.cos(phi)
      
      // 霓虹绿色到蓝色的渐变
      const colorMix = Math.random()
      colors[i * 3] = 0 + colorMix * 0 // R
      colors[i * 3 + 1] = 1 - colorMix * 0.3 // G
      colors[i * 3 + 2] = 0.5 + colorMix * 0.5 // B
    }
    
    return { positions, colors }
  }, [])

  useFrame((state) => {
    if (points.current) {
      points.current.rotation.y = state.clock.elapsedTime * 0.05
      points.current.rotation.x = Math.sin(state.clock.elapsedTime * 0.1) * 0.1
    }
  })

  return (
    <points ref={points}>
      <bufferGeometry>
        <bufferAttribute
          attach="attributes-position"
          count={particleCount}
          array={particles.positions}
          itemSize={3}
        />
        <bufferAttribute
          attach="attributes-color"
          count={particleCount}
          array={particles.colors}
          itemSize={3}
        />
      </bufferGeometry>
      <pointsMaterial
        size={0.08}
        vertexColors
        transparent
        opacity={0.8}
        sizeAttenuation
        blending={THREE.AdditiveBlending}
      />
    </points>
  )
}

// 动态网格组件
function DynamicGrid() {
  const gridRef = useRef()
  
  useFrame((state) => {
    if (gridRef.current) {
      gridRef.current.rotation.z = state.clock.elapsedTime * 0.02
    }
  })

  return (
    <group ref={gridRef}>
      <gridHelper
        args={[40, 40, '#00ff88', '#00ff88']}
        position={[0, -8, 0]}
        rotation={[0, 0, 0]}
      />
    </group>
  )
}

// 数据流组件
function DataStream() {
  const linesRef = useRef()
  const lineCount = 50

  const lines = useMemo(() => {
    const positions = []
    for (let i = 0; i < lineCount; i++) {
      const x = (Math.random() - 0.5) * 30
      const z = (Math.random() - 0.5) * 30
      const y = -10 + Math.random() * 20
      
      positions.push(x, y, z)
      positions.push(x, y + 2, z)
    }
    return new Float32Array(positions)
  }, [])

  useFrame((state) => {
    if (linesRef.current) {
      const positions = linesRef.current.geometry.attributes.position.array
      for (let i = 0; i < lineCount; i++) {
        positions[i * 6 + 1] += 0.05
        positions[i * 6 + 4] += 0.05
        
        if (positions[i * 6 + 1] > 10) {
          positions[i * 6 + 1] = -10
          positions[i * 6 + 4] = -8
        }
      }
      linesRef.current.geometry.attributes.position.needsUpdate = true
    }
  })

  return (
    <lineSegments ref={linesRef}>
      <bufferGeometry>
        <bufferAttribute
          attach="attributes-position"
          count={lineCount * 2}
          array={lines}
          itemSize={3}
        />
      </bufferGeometry>
      <lineBasicMaterial
        color="#00ff88"
        transparent
        opacity={0.3}
        blending={THREE.AdditiveBlending}
      />
    </lineSegments>
  )
}

// 主场景组件
function Scene() {
  return (
    <>
      <ambientLight intensity={0.5} />
      <pointLight position={[10, 10, 10]} intensity={1} color="#00ff88" />
      <ParticleField />
      <DynamicGrid />
      <DataStream />
    </>
  )
}

// 导出的背景组件
export default function HolographicBackground() {
  return (
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      width: '100%',
      height: '100%',
      zIndex: 0,
      pointerEvents: 'none',
    }}>
      <Canvas
        camera={{ position: [0, 0, 20], fov: 60 }}
        style={{ background: 'transparent' }}
      >
        <Scene />
      </Canvas>
    </div>
  )
}
