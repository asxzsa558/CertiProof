import { useRef, useState, useEffect } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { Text } from '@react-three/drei'
import * as THREE from 'three'
import VeriSureLogo from './VeriSureLogo'

function Medal() {
  const groupRef = useRef()
  const ringRef = useRef()

  useFrame((state, delta) => {
    if (groupRef.current) {
      groupRef.current.rotation.y += delta * 0.4
    }
    if (ringRef.current) {
      ringRef.current.rotation.z -= delta * 0.2
    }
  })

  return (
    <group ref={groupRef}>
      {/* 外圈金边 - 类似 CIA 徽章的金色描边 */}
      <mesh ref={ringRef} rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[1, 0.06, 16, 64]} />
        <meshStandardMaterial 
          color="#C5A55A" 
          metalness={0.95} 
          roughness={0.15}
          emissive="#C5A55A"
          emissiveIntensity={0.2}
        />
      </mesh>

      {/* 主圆盘 - 深蓝底色，像 CIA 徽章的深色底 */}
      <mesh rotation={[Math.PI / 2, 0, 0]}>
        <cylinderGeometry args={[0.92, 0.92, 0.12, 64]} />
        <meshStandardMaterial 
          color="#0B1D3A" 
          metalness={0.7} 
          roughness={0.25}
          emissive="#0B1D3A"
          emissiveIntensity={0.15}
        />
      </mesh>

      {/* 中心 "V" 字母 - 代表 VeriSure */}
      <Text
        position={[0, 0.08, 0.08]}
        fontSize={0.5}
        color="#C5A55A"
        anchorX="center"
        anchorY="middle"
        font={undefined}
        letterSpacing={0.05}
      >
        V
      </Text>

      {/* 上弧文字 "VERISURE" - 类似 CIA 的 CENTRAL INTELLIGENCE */}
      <Text
        position={[0, 0.08, 0.08]}
        rotation={[0, 0, 0]}
        fontSize={0.08}
        color="#C5A55A"
        anchorX="center"
        anchorY="middle"
        maxWidth={2}
      >
        VERISURE
      </Text>

      {/* 下弧文字 */}
      <Text
        position={[0, -0.15, 0.08]}
        fontSize={0.06}
        color="#C5A55A"
        anchorX="center"
        anchorY="middle"
        maxWidth={2}
      >
        INTELLIGENCE
      </Text>
    </group>
  )
}

function VeriSureLogo3D({ size = 56 }) {
  const [webglSupported, setWebglSupported] = useState(null)

  useEffect(() => {
    try {
      const canvas = document.createElement('canvas')
      const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl')
      setWebglSupported(!!gl)
    } catch (e) {
      setWebglSupported(false)
    }
  }, [])

  if (webglSupported === false) {
    return <VeriSureLogo size={size} />
  }

  if (webglSupported === null) {
    return <div style={{ width: size, height: size }} />
  }

  return (
    <div style={{ width: size, height: size }}>
      <Canvas
        camera={{ position: [0, 0, 2.2], fov: 50 }}
        style={{ background: 'transparent' }}
        onError={() => setWebglSupported(false)}
      >
        <hemisphereLight args={['#C5A55A', '#0B1D3A', 0.8]} />
        <pointLight position={[3, 3, 5]} intensity={1.2} color="#C5A55A" />
        <pointLight position={[-3, -3, 3]} intensity={0.6} color="#1A3A6B" />
        <pointLight position={[0, 0, 5]} intensity={0.8} color="#ffffff" />
        <Medal />
      </Canvas>
    </div>
  )
}

export default VeriSureLogo3D
