import { useRef, useState, useEffect } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import VeriSureLogo from './VeriSureLogo'

function Shield() {
  const meshRef = useRef()
  
  useFrame((state, delta) => {
    if (meshRef.current) {
      meshRef.current.rotation.y += delta * 0.3
    }
  })

  const shieldShape = new THREE.Shape()
  shieldShape.moveTo(0, 0.8)
  shieldShape.lineTo(0.6, 0.5)
  shieldShape.lineTo(0.6, -0.2)
  shieldShape.quadraticCurveTo(0.6, -0.6, 0, -0.8)
  shieldShape.quadraticCurveTo(-0.6, -0.6, -0.6, -0.2)
  shieldShape.lineTo(-0.6, 0.5)
  shieldShape.lineTo(0, 0.8)

  const extrudeSettings = {
    depth: 0.15,
    bevelEnabled: true,
    bevelThickness: 0.02,
    bevelSize: 0.02,
    bevelSegments: 3,
  }

  return (
    <group ref={meshRef}>
      {/* 外圈圆环 */}
      <mesh rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[1, 0.08, 16, 64]} />
        <meshStandardMaterial 
          color="#C5A55A" 
          metalness={0.8} 
          roughness={0.2}
        />
      </mesh>

      {/* 盾牌主体 */}
      <mesh position={[0, 0, 0]}>
        <extrudeGeometry args={[shieldShape, extrudeSettings]} />
        <meshStandardMaterial 
          color="#1A3A6B" 
          metalness={0.6} 
          roughness={0.3}
          emissive="#1A3A6B"
          emissiveIntensity={0.3}
        />
      </mesh>

      {/* 对勾 */}
      <mesh position={[0, 0, 0.1]} rotation={[0, 0, 0]}>
        <tubeGeometry args={[
          new THREE.CatmullRomCurve3([
            new THREE.Vector3(-0.3, 0, 0),
            new THREE.Vector3(-0.1, -0.25, 0),
            new THREE.Vector3(0.35, 0.25, 0),
          ]),
          20,
          0.04,
          8,
          false
        ]} />
        <meshStandardMaterial 
          color="#C5A55A" 
          metalness={0.9} 
          roughness={0.1}
          emissive="#C5A55A"
          emissiveIntensity={0.2}
        />
      </mesh>
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
        camera={{ position: [0, 0, 2.5], fov: 60 }}
        style={{ background: 'transparent' }}
        onError={() => setWebglSupported(false)}
      >
        <hemisphereLight args={['#C5A55A', '#0B1D3A', 1.0]} />
        <pointLight position={[5, 5, 5]} intensity={1.5} color="#C5A55A" />
        <pointLight position={[-5, -5, 5]} intensity={0.8} color="#1A3A6B" />
        <pointLight position={[0, 5, -5]} intensity={0.5} color="#ffffff" />
        <Shield />
      </Canvas>
    </div>
  )
}

export default VeriSureLogo3D
