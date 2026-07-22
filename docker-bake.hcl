variable "CERTIPROOF_IMAGE_PREFIX" {
  default = "certiproof"
}

variable "CERTIPROOF_VERSION" {
  default = "latest"
}

variable "CERTIPROOF_PLATFORMS" {
  default = "linux/amd64"
}

target "_cloud" {
  platforms = split(",", CERTIPROOF_PLATFORMS)
}

target "postgres" {
  inherits   = ["_cloud"]
  context    = "./docker/postgres"
  dockerfile = "Dockerfile"
  tags       = ["${CERTIPROOF_IMAGE_PREFIX}/postgres:${CERTIPROOF_VERSION}"]
}

target "backend" {
  inherits   = ["_cloud"]
  context    = "./backend"
  dockerfile = "Dockerfile"
  tags       = ["${CERTIPROOF_IMAGE_PREFIX}/backend:${CERTIPROOF_VERSION}"]
}

target "frontend" {
  inherits   = ["_cloud"]
  context    = "./frontend"
  dockerfile = "Dockerfile"
  tags       = ["${CERTIPROOF_IMAGE_PREFIX}/frontend:${CERTIPROOF_VERSION}"]
}

target "mcp-gateway" {
  inherits   = ["_cloud"]
  context    = "./mcp-servers/gateway"
  dockerfile = "Dockerfile"
  tags       = ["${CERTIPROOF_IMAGE_PREFIX}/mcp-gateway:${CERTIPROOF_VERSION}"]
}

target "security-tools" {
  inherits   = ["_cloud"]
  context    = "./mcp-servers/security-tools"
  dockerfile = "Dockerfile"
  tags       = ["${CERTIPROOF_IMAGE_PREFIX}/security-tools:${CERTIPROOF_VERSION}"]
}

target "ssh-checker" {
  inherits   = ["_cloud"]
  context    = "./mcp-servers/ssh-checker"
  dockerfile = "Dockerfile"
  tags       = ["${CERTIPROOF_IMAGE_PREFIX}/ssh-checker:${CERTIPROOF_VERSION}"]
}

target "fast-scanner" {
  inherits   = ["_cloud"]
  context    = "./mcp-servers/fast-scanner"
  dockerfile = "Dockerfile"
  tags       = ["${CERTIPROOF_IMAGE_PREFIX}/fast-scanner:${CERTIPROOF_VERSION}"]
}

target "web-tools" {
  inherits   = ["_cloud"]
  context    = "./mcp-servers/web-tools"
  dockerfile = "Dockerfile"
  tags       = ["${CERTIPROOF_IMAGE_PREFIX}/web-tools:${CERTIPROOF_VERSION}"]
}

target "network-tools" {
  inherits   = ["_cloud"]
  context    = "./mcp-servers/network-tools"
  dockerfile = "Dockerfile"
  tags       = ["${CERTIPROOF_IMAGE_PREFIX}/network-tools:${CERTIPROOF_VERSION}"]
}

target "db-tools" {
  inherits   = ["_cloud"]
  context    = "./mcp-servers/db-tools"
  dockerfile = "Dockerfile"
  tags       = ["${CERTIPROOF_IMAGE_PREFIX}/db-tools:${CERTIPROOF_VERSION}"]
}

target "windows-tools" {
  inherits   = ["_cloud"]
  context    = "./mcp-servers/windows-tools"
  dockerfile = "Dockerfile"
  tags       = ["${CERTIPROOF_IMAGE_PREFIX}/windows-tools:${CERTIPROOF_VERSION}"]
}

target "ocr-server" {
  inherits   = ["_cloud"]
  context    = "./mcp-servers/ocr-server"
  dockerfile = "Dockerfile"
  tags       = ["${CERTIPROOF_IMAGE_PREFIX}/ocr-server:${CERTIPROOF_VERSION}"]
}

target "embedding-server" {
  inherits   = ["_cloud"]
  context    = "./mcp-servers/embedding-server"
  dockerfile = "Dockerfile"
  tags       = ["${CERTIPROOF_IMAGE_PREFIX}/embedding-server:${CERTIPROOF_VERSION}"]
}

group "default" {
  targets = [
    "postgres", "backend", "frontend", "mcp-gateway", "security-tools",
    "ssh-checker", "fast-scanner", "web-tools", "network-tools", "db-tools",
    "windows-tools", "ocr-server", "embedding-server"
  ]
}

group "remote-node" {
  targets = [
    "backend", "mcp-gateway", "security-tools", "ssh-checker", "fast-scanner",
    "web-tools", "network-tools", "db-tools", "windows-tools"
  ]
}
