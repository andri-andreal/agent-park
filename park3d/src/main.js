// Agent Park 3D: the terminal park as a low-poly 3D world.
//
// The state (who is around, working, waiting) comes from park_state.py via
// the Tauri app; how the animals move is simulated here, like the terminal
// view simulates its own. Open with ?demo in a plain browser to try it out.
import * as THREE from "three"
import { OrbitControls } from "three/addons/controls/OrbitControls.js"
import { CSS2DObject, CSS2DRenderer } from "three/addons/renderers/CSS2DRenderer.js"
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js"

const PARK = { left: -30, right: 9, depth: 22 }  // where idle animals roam
const OFFICE = { left: 13, right: 34, depth: 15 }  // the fenced AI office
const DESKS = [17, 26].flatMap((x) => [-9, -3, 3, 9].map((z) => new THREE.Vector3(x, 0, z)))
const SEAT = 2.5  // how far in front of its desk a working animal sits
const EDGE = 58  // leaving animals walk this far out, then vanish
const WORK_SAY = ["tik tak tuk!", "ngoding!!", "wusss!", "sibuk sibuk!", "compile!", "gas terus!"]
const SCREEN_TEXT = [">_ make", "{ ok! }", "[###  ]", "[#### ]", "git add", "404?!..", ">_ test", "[#####]"]
const STALE = 5000  // ms without state before the page says the feed stopped
const OPTIONS = new URLSearchParams(location.search)
// 30 frames a second is plenty for a screensaver; ?smooth for 60, ?cap=0 for no limit.
const FPS_CAP = OPTIONS.has("smooth") ? 0 : Number(OPTIONS.get("cap") ?? 30)
// ?low trades shadows and smooth edges for speed on weak GPUs.
const LOW = OPTIONS.has("low")

// --- scene ------------------------------------------------------------------

const renderer = new THREE.WebGLRenderer({ antialias: !LOW, powerPreference: "high-performance" })
renderer.setPixelRatio(LOW ? 1 : Math.min(devicePixelRatio, 1.5))
renderer.setSize(innerWidth, innerHeight)
renderer.shadowMap.enabled = !LOW
renderer.shadowMap.type = THREE.BasicShadowMap  // crisp edges suit low-poly, and cost one sample
// Animals move slowly: redrawing the shadow map every third frame is enough.
renderer.shadowMap.autoUpdate = false
const SHADOW_EVERY = 3
renderer.domElement.className = "scene"
document.body.prepend(renderer.domElement)

const labels = new CSS2DRenderer()
labels.setSize(innerWidth, innerHeight)
Object.assign(labels.domElement.style, { position: "fixed", top: "0", pointerEvents: "none" })
document.body.append(labels.domElement)

const scene = new THREE.Scene()
scene.background = new THREE.Color("#9fd3f0")
scene.fog = new THREE.Fog("#9fd3f0", 60, 120)

const camera = new THREE.PerspectiveCamera(45, innerWidth / innerHeight, 0.1, 400)
camera.position.set(-6, 22, 36)
const controls = new OrbitControls(camera, renderer.domElement)
controls.target.set(2, 0, 0)
controls.enableDamping = true
controls.autoRotate = true
controls.autoRotateSpeed = 0.35
controls.maxPolarAngle = Math.PI * 0.45
controls.minDistance = 15
controls.maxDistance = 90

scene.add(new THREE.HemisphereLight("#dff2ff", "#4f7a3a", 1.4))
const sun = new THREE.DirectionalLight("#fff4dc", 2.2)
sun.position.set(-30, 50, 25)
sun.castShadow = true
sun.shadow.mapSize.set(1024, 1024)
Object.assign(sun.shadow.camera, { left: -60, right: 60, top: 60, bottom: -60 })
scene.add(sun)

// One material per colour, so parts of the same colour can be merged and drawn at once.
const materials = new Map()
function flat(color) {
  const key = new THREE.Color(color).getHexString()
  if (!materials.has(key)) materials.set(key, new THREE.MeshLambertMaterial({ color: `#${key}`, flatShading: true }))
  return materials.get(key)
}

// Merges every mesh under `root` into one mesh per material, except meshes
// marked userData.keep (moving legs, screens). Hundreds of draw calls become a few.
function bake(root) {
  root.updateMatrixWorld(true)
  const inverse = root.matrixWorld.clone().invert(), parts = new Map(), merged = []
  root.traverse((part) => {
    if (part.isMesh && !part.userData.keep) parts.set(part.material, [...(parts.get(part.material) || []), part])
  })
  for (const [material, meshes] of parts) {
    const geometries = meshes.map((part) => {
      const geometry = part.geometry.index ? part.geometry.toNonIndexed() : part.geometry.clone()
      return geometry.applyMatrix4(inverse.clone().multiply(part.matrixWorld))
    })
    meshes.forEach((part) => part.removeFromParent())
    merged.push(mesh(mergeGeometries(geometries), material))
  }
  root.add(...merged)
  return root
}

function mesh(geometry, material, x = 0, y = 0, z = 0) {
  const part = new THREE.Mesh(geometry, material)
  part.position.set(x, y, z)
  part.castShadow = part.receiveShadow = true
  return part
}

function label(text, className = "label") {
  const element = document.createElement("div")
  element.className = className
  element.textContent = text
  return new CSS2DObject(element)
}

// A small seeded random, so the trees stand in the same place every time.
let seed = 7
const random = () => ((seed = (seed * 16807) % 2147483647) - 1) / 2147483646

function buildPark() {
  const ground = mesh(new THREE.CircleGeometry(EDGE + 6, 64), flat("#6db55a"))
  ground.rotation.x = -Math.PI / 2
  ground.castShadow = false
  scene.add(ground)
  const park = new THREE.Group()
  const path = mesh(new THREE.PlaneGeometry(26, 3.2), flat("#d9c391"), 0, 0.01, 0)
  path.rotation.x = -Math.PI / 2
  park.add(path)
  const trunk = flat("#7a5232"), leaves = [flat("#3f8f3a"), flat("#57a843"), flat("#2f7a3a")]
  // Trees ring the park, outside where the orbiting camera looks from.
  for (let placed = 0; placed < 40;) {
    const angle = random() * Math.PI * 2, radius = 44 + random() * 14
    const x = Math.cos(angle) * radius, z = Math.sin(angle) * radius
    if (x > OFFICE.left - 4 && Math.abs(z) < OFFICE.depth + 4) continue  // keep the office clear
    const tree = new THREE.Group(), height = 2.5 + random() * 2
    tree.add(mesh(new THREE.CylinderGeometry(0.25, 0.35, height, 6), trunk, 0, height / 2, 0))
    tree.add(mesh(new THREE.ConeGeometry(1.6 + random(), 3.5 + random() * 2, 7), leaves[placed % 3], 0, height + 1.5, 0))
    tree.position.set(x, 0, z)
    park.add(tree)
    placed++
  }
  const wood = flat("#9b6b3d")
  for (const [x, z, turn] of [[-12, -6, 0], [-4, 8, Math.PI], [-20, 4, Math.PI / 2]]) {
    const bench = new THREE.Group()
    bench.add(mesh(new THREE.BoxGeometry(3, 0.2, 0.9), wood, 0, 0.7, 0))
    bench.add(mesh(new THREE.BoxGeometry(3, 0.8, 0.15), wood, 0, 1.2, -0.4))
    for (const side of [-1.3, 1.3]) bench.add(mesh(new THREE.BoxGeometry(0.15, 0.7, 0.8), wood, side, 0.35, 0))
    bench.position.set(x, 0, z)
    bench.rotation.y = turn
    park.add(bench)
  }
  scene.add(bake(park))
}

const desks = []  // { position, screen, context, texture }

function buildOffice() {
  const width = OFFICE.right - OFFICE.left, office = new THREE.Group()
  const floor = mesh(new THREE.BoxGeometry(width, 0.2, OFFICE.depth * 2), flat("#c9ccd1"),
    (OFFICE.left + OFFICE.right) / 2, 0.1, 0)
  office.add(floor)
  const post = new THREE.CylinderGeometry(0.12, 0.12, 1.4, 6), white = flat("#f2efe6")
  for (let x = OFFICE.left; x <= OFFICE.right; x += 1.5) {
    for (const z of [-OFFICE.depth, OFFICE.depth]) office.add(mesh(post, white, x, 0.7, z))
  }
  for (let z = -OFFICE.depth; z <= OFFICE.depth; z += 1.5) {
    if (Math.abs(z) > 3) office.add(mesh(post, white, OFFICE.left, 0.7, z))  // leave a gate
    office.add(mesh(post, white, OFFICE.right, 0.7, z))
  }
  const top = flat("#8a5a3b"), metal = flat("#3c4650"), case_ = flat("#e6e6e6")
  for (const position of DESKS) {
    const desk = new THREE.Group()
    desk.add(mesh(new THREE.BoxGeometry(1.4, 0.12, 2.4), top, 0, 1.0, 0))
    for (const [x, z] of [[-0.6, -1.1], [0.6, -1.1], [-0.6, 1.1], [0.6, 1.1]]) {
      desk.add(mesh(new THREE.BoxGeometry(0.1, 1.0, 0.1), metal, x, 0.5, z))
    }
    desk.add(mesh(new THREE.BoxGeometry(0.2, 1.1, 1.7), case_, 0.35, 1.7, 0))
    desk.add(mesh(new THREE.BoxGeometry(0.3, 0.3, 0.3), metal, 0.4, 1.2, 0))
    const canvas = document.createElement("canvas")
    canvas.width = 128
    canvas.height = 80
    const texture = new THREE.CanvasTexture(canvas)
    const screen = new THREE.Mesh(new THREE.PlaneGeometry(1.5, 0.9),
      new THREE.MeshBasicMaterial({ map: texture }))
    screen.position.set(0.24, 1.72, 0)
    screen.rotation.y = -Math.PI / 2
    screen.userData.keep = true
    desk.add(screen)
    desk.position.copy(position).setY(0.2)
    office.add(desk)
    desks.push({ position, context: canvas.getContext("2d"), texture, user: null, shown: "" })
    drawScreen(desks.at(-1), "  zz", "#55606a")
  }
  scene.add(bake(office))
  const sign = label("MARKAS AI", "sign")
  sign.position.set((OFFICE.left + OFFICE.right) / 2, 5, -OFFICE.depth)
  scene.add(sign)
  return sign
}

// The free desk farthest from the taken ones, so neighbours' labels never overlap.
function pickDesk() {
  const taken = desks.filter((desk) => desk.user)
  let best = null, gap = -1
  for (const desk of desks) {
    if (desk.user) continue
    const nearest = Math.min(...taken.map((other) => other.position.distanceTo(desk.position)))
    if (nearest > gap) [best, gap] = [desk, nearest]
  }
  return best
}

function drawScreen(desk, text, color) {
  if (desk.shown === text + color) return  // uploading a texture every frame is costly
  desk.shown = text + color
  const { context } = desk
  context.fillStyle = "#0d1418"
  context.fillRect(0, 0, 128, 80)
  context.fillStyle = color
  context.font = "bold 20px monospace"
  context.fillText(text, 10, 48)
  desk.texture.needsUpdate = true
}

// --- animals -----------------------------------------------------------------

// Everything faces +x; legs hang from pivots so they can swing.
function buildAnimal(species, color, baby) {
  const body = flat(color), dark = flat("#2a2420"), light = flat("#f5efe4"), beak = flat("#f2a33a")
  const group = new THREE.Group(), legs = []
  const leg = (x, z, height, material = body, radius = 0.12) => {
    const geometry = new THREE.CylinderGeometry(radius, radius, height, 6).translate(0, -height / 2, 0)
    const part = mesh(geometry, material, x, height, z)
    part.userData.keep = true
    legs.push(part)
    group.add(part)
  }
  const eyes = (x, y, spread, size = 0.07) => {
    for (const side of [-1, 1]) group.add(mesh(new THREE.SphereGeometry(size, 6, 4), dark, x, y, side * spread))
  }
  if (species === "bebek") {
    group.add(mesh(new THREE.SphereGeometry(0.6, 8, 6).scale(1.3, 0.85, 1), body, 0, 0.9, 0))
    group.add(mesh(new THREE.SphereGeometry(0.38, 8, 6), body, 0.6, 1.55, 0))
    group.add(mesh(new THREE.BoxGeometry(0.4, 0.1, 0.3), beak, 1.0, 1.5, 0))
    group.add(mesh(new THREE.ConeGeometry(0.2, 0.45, 5).rotateZ(Math.PI / 2.4), body, -0.8, 1.1, 0))
    eyes(0.86, 1.65, 0.18)
    leg(0, -0.2, 0.45, beak, 0.07)
    leg(0, 0.2, 0.45, beak, 0.07)
  } else {
    const shapes = {
      kucing: { size: [1.3, 0.6, 0.6], head: 0.42, height: 0.55 },
      anjing: { size: [1.45, 0.7, 0.7], head: 0.45, height: 0.6 },
      kelinci: { size: [1.0, 0.75, 0.7], head: 0.4, height: 0.35 },
      tikus: { size: [1.1, 0.5, 0.55], head: 0.32, height: 0.3 },
    }
    const { size: [length, tall, wide], head, height } = shapes[species] || shapes.kucing
    const middle = height + tall / 2
    const torso = species === "kelinci" || species === "tikus"
      ? new THREE.SphereGeometry(0.5, 8, 6).scale(length, tall * 1.6, wide * 1.6)
      : new THREE.BoxGeometry(length, tall, wide)
    group.add(mesh(torso, body, 0, middle, 0))
    const headX = length / 2 + head * 0.5, headY = middle + tall * 0.45
    group.add(mesh(new THREE.SphereGeometry(head, 8, 6), body, headX, headY, 0))
    eyes(headX + head * 0.82, headY + head * 0.2, head * 0.42)
    group.add(mesh(new THREE.SphereGeometry(0.06, 5, 4), dark, headX + head, headY - head * 0.1, 0))  // nose
    for (const side of [-1, 1]) {
      const z = side * head * 0.5
      if (species === "kucing") {
        group.add(mesh(new THREE.ConeGeometry(0.16, 0.36, 4), body, headX - 0.05, headY + head * 0.95, z))
      } else if (species === "anjing") {
        const ear = mesh(new THREE.BoxGeometry(0.18, 0.45, 0.12), flat(new THREE.Color(color).multiplyScalar(0.7)),
          headX - 0.1, headY + head * 0.2, side * (head + 0.04))
        ear.rotation.x = side * 0.3
        group.add(ear)
        group.add(mesh(new THREE.BoxGeometry(0.35, 0.25, 0.3), body, headX + head * 0.8, headY - 0.12, 0))
      } else if (species === "kelinci") {
        const ear = mesh(new THREE.CapsuleGeometry(0.1, 0.7, 3, 6), body, headX - 0.1, headY + head + 0.4, z * 0.7)
        ear.rotation.x = side * 0.15
        group.add(ear)
      } else if (species === "tikus") {
        const ear = mesh(new THREE.CylinderGeometry(0.2, 0.2, 0.04, 10), light, headX - 0.05, headY + head * 0.75, side * head * 0.75)
        ear.rotation.x = Math.PI / 2
        group.add(ear)
      }
    }
    if (species === "kelinci") {
      group.add(mesh(new THREE.SphereGeometry(0.2, 6, 5), light, -length / 2 - 0.05, middle + 0.1, 0))
    } else {
      const thin = species === "tikus" ? 0.04 : 0.08, long = species === "tikus" ? 1.3 : species === "anjing" ? 0.5 : 0.9
      const tail = mesh(new THREE.CylinderGeometry(thin, thin, long, 5).translate(0, long / 2, 0), body,
        -length / 2, middle + tall * 0.2, 0)
      tail.rotation.z = species === "tikus" ? 1.35 : species === "anjing" ? 0.5 : 0.7
      group.add(tail)
    }
    for (const x of [length / 2 - 0.2, -length / 2 + 0.2]) {
      for (const z of [-wide / 2 + 0.12, wide / 2 - 0.12]) leg(x, z, height)
    }
  }
  bake(group)
  group.scale.setScalar(baby ? 0.85 : 1.5)
  return { group, legs }
}

const animals = new Map()  // id -> animal
const log = document.getElementById("log")

// Writing the same text again still makes the browser lay the page out anew.
function setText(element, text) {
  if (element.textContent !== text) element.textContent = text
}

function say(text) {
  const line = document.createElement("div")
  line.textContent = text
  log.append(line)
  setTimeout(() => line.remove(), 8000)
  while (log.children.length > 5) log.firstChild.remove()
}

function parkSpot() {
  const x = PARK.left + Math.random() * (PARK.right - PARK.left)
  return new THREE.Vector3(x, 0, (Math.random() * 2 - 1) * PARK.depth)
}

function addAnimal(id, info, parent = null) {
  const baby = Boolean(parent)
  const { group, legs } = buildAnimal(baby ? parent.species : info.species, parent?.color || info.color, baby)
  const name = label(baby ? info.type : info.name, baby ? "label sub" : "label")
  const model = document.createElement("span")
  model.className = "model"
  const speech = document.createElement("span")
  speech.className = "say"
  name.element.append(model, speech)
  name.position.set(0, 2.6, 0)
  group.add(name)
  const start = parent ? parent.group.position.clone() : parkSpot()
  group.position.copy(start).setY(parent ? 0 : 30)  // grown-ups drop in from the sky
  scene.add(group)
  const animal = {
    id, group, legs, name, model, speech, baby, parent, species: parent?.species || info.species, color: parent?.color || info.color,
    label: info.name, status: info.status || "idle", target: parkSpot(), rest: 0, desk: null,
    phase: Math.random() * 10, falling: !parent, velocity: 0, leaving: false, seen: true,
  }
  animals.set(id, animal)
  if (!parent) say(`${info.name} jatuh dari langit ke taman!`)
  return animal
}

function leave(animal, words) {
  if (animal.leaving) return
  animal.leaving = true
  freeDesk(animal)
  const away = animal.group.position.clone().setY(0)
  if (away.lengthSq() < 1) away.set(-1, 0, 0)
  animal.target = away.normalize().multiplyScalar(EDGE + 4)
  if (words) say(words)
}

function freeDesk(animal) {
  if (animal.desk) {
    animal.desk.user = null
    drawScreen(animal.desk, "  zz", "#55606a")
    animal.desk = null
  }
}

// --- state from park_state.py -------------------------------------------------

let lastState = 0
const message = document.getElementById("message")

function apply(state) {
  lastState = performance.now()
  for (const animal of animals.values()) animal.seen = false
  for (const info of state.agents) {
    const animal = animals.get(info.id) || addAnimal(info.id, info)
    animal.seen = true
    if (animal.status !== "wait" && info.status === "wait") say(`${info.name} butuh persetujuan kamu!`)
    animal.status = info.status
    setText(animal.model, info.model || "")
    for (const sub of info.subagents) {
      const id = `${info.id}/${sub.id}`
      if (!animals.has(id)) {
        addAnimal(id, sub, animal)
        say(`${info.name} memanggil ${sub.type} untuk membantu!`)
      }
      animals.get(id).seen = true
    }
  }
  for (const animal of animals.values()) {
    if (!animal.seen) leave(animal, animal.baby ? null : `${animal.label} selesai kerja. Dadah!`)
  }
  for (const monster of state.monsters || []) say(`Monster ${monster.name} (${monster.detail}) mengintip taman...`)
  if (state.system) showSystem(state.system)
  const working = state.agents.filter((agent) => agent.status === "work").length
  sign.element.textContent = `MARKAS AI: ${working} kerja`
  message.textContent = state.agents.length ? "" : "Taman sepi... jalankan agen AI, hewannya akan datang."
}

const systemPanel = document.getElementById("system")
const spark = document.getElementById("spark").getContext("2d")

function showSystem(system) {
  systemPanel.hidden = false
  const level = (value, busy, alarm) => (value >= alarm ? "var(--alarm)" : value >= busy ? "var(--busy)" : "var(--calm)")
  const ram = system.ram[1] ? system.ram[0] / system.ram[1] : 0
  for (const [name, value, color] of [["cpu", system.cpu, level(system.cpu, 0.6, 0.85)], ["ram", ram, level(ram, 0.75, 0.9)]]) {
    document.getElementById(`${name}-bar`).style.width = `${Math.round(value * 100)}%`
    document.getElementById(`${name}-bar`).style.background = color
    document.getElementById(`${name}-text`).textContent = `${Math.round(value * 100)}%`
  }
  spark.clearRect(0, 0, 200, 36)
  spark.fillStyle = "#6fd17a"
  const history = system.history.slice(-24)
  history.forEach((cpu, index) => spark.fillRect(index * (200 / 24), 36 - cpu * 34, 200 / 24 - 2, cpu * 34 + 1))
  document.getElementById("mood").textContent = {
    calm: "Kucing penjaga: santai~", busy: "Kucing penjaga: CPU naik nih...",
    alarm: `Kucing penjaga: AWAS! CPU ${Math.round(system.cpu * 100)}%!`,
  }[system.mood] + `  ·  load ${system.load.toFixed(2)}`
}

async function connect() {
  if (window.__TAURI_INTERNALS__) {
    const { listen } = await import("@tauri-apps/api/event")
    await listen("park-state", (event) => apply(JSON.parse(event.payload)))
  } else if (new URLSearchParams(location.search).has("demo")) {
    demo()
  } else {
    message.textContent = "Bukan di aplikasi Tauri. Buka dengan ?demo untuk contoh."
  }
}

// A made-up park for trying the page in a browser.
function demo() {
  const cast = [
    { id: "1", kind: "claude", name: "Claude", species: "kucing", color: "#ff8700", model: "opus-5-5" },
    { id: "2", kind: "codex", name: "Codex", species: "anjing", color: "#00afff", model: "gpt-6.1-sol" },
    { id: "3", kind: "opencode", name: "OpenCode", species: "kelinci", color: "#af87ff", model: "MiniMax-M3.1-Flash" },
    { id: "4", kind: "kiro-cli", name: "Kiro", species: "tikus", color: "#875fff", model: "auto" },
    { id: "5", kind: "pi", name: "Pi", species: "bebek", color: "#00d7ff", model: "glm-5.2" },
  ]
  const history = []
  let tick = 0
  const step = () => {
    tick++
    const cpu = 0.3 + 0.25 * Math.sin(tick / 6) + Math.random() * 0.1
    history.push(cpu)
    apply({
      agents: cast.slice(0, Math.min(cast.length, 1 + Math.floor(tick / 2))).map((agent, index) => ({
        ...agent,
        status: ["work", "idle", "work", "wait", "idle"][(index + Math.floor(tick / 45)) % 5],
        subagents: index === 0 && tick % 30 > 8 ? [{ id: "a1", type: "Explore" }] : [],
      })),
      system: { cpu, ram: [11e9, 32e9], swap: [0, 0], load: cpu * 8, history: history.slice(-24), mood: cpu > 0.6 ? "busy" : "calm" },
      monsters: [],
    })
  }
  step()
  setInterval(step, 1000)
}

// --- simulation -------------------------------------------------------------------

function walkTo(animal, target, speed, dt) {
  const position = animal.group.position
  const offset = target.clone().sub(position).setY(0)
  const distance = offset.length()
  if (distance < 0.15) return true
  const step = Math.min(distance, speed * dt)
  position.addScaledVector(offset.normalize(), step)
  turnTo(animal, Math.atan2(-offset.z, offset.x), dt)
  animal.phase += step * 2.2
  animal.legs.forEach((leg, index) => (leg.rotation.z = Math.sin(animal.phase + (index % 2) * Math.PI) * 0.6))
  return false
}

function turnTo(animal, angle, dt) {
  const current = animal.group.rotation.y
  const delta = Math.atan2(Math.sin(angle - current), Math.cos(angle - current))
  animal.group.rotation.y = current + delta * Math.min(1, dt * 8)
}

function still(animal) {
  animal.legs.forEach((leg) => (leg.rotation.z *= 0.8))
}

function update(animal, dt, time) {
  const position = animal.group.position
  if (animal.falling) {
    animal.velocity += 30 * dt
    position.y = Math.max(0, position.y - animal.velocity * dt)
    animal.group.rotation.y += dt * 6
    if (position.y === 0) {
      animal.falling = false
      setText(animal.speech, "ugh, pusing...")
      animal.rest = 1.5
    }
    return
  }
  if (animal.leaving) {
    setText(animal.speech, animal.baby ? "" : "dadah!")
    if (walkTo(animal, animal.target, 7, dt)) {
      scene.remove(animal.group)
      animal.name.element.remove()
      animals.delete(animal.id)
    }
    return
  }
  if (animal.baby) {
    // Babies scamper in loops around the animal that called them.
    const parent = animal.parent
    if (!animals.has(parent.id)) return leave(animal)
    const angle = time * 1.4 + animal.phase
    const spot = parent.group.position.clone().add(new THREE.Vector3(Math.cos(angle) * 2.6, 0, Math.sin(angle) * 2.6))
    walkTo(animal, spot, 9, dt)
    position.y = Math.abs(Math.sin(time * 8 + animal.phase)) * 0.3
    return
  }
  position.y = 0
  animal.name.element.classList.toggle("wait", animal.status === "wait")
  if (animal.status === "wait") {
    freeDesk(animal)
    position.y = Math.abs(Math.sin(time * 6 + animal.phase)) * 1.2  // jump for attention
    still(animal)
    turnTo(animal, Math.atan2(-(camera.position.z - position.z), camera.position.x - position.x), dt)
    setText(animal.speech, Math.floor(time * 2) % 2 ? "butuh kamu!" : "halo? izin dong!")
    return
  }
  if (animal.status === "work") {
    if (!animal.desk) {
      animal.desk = pickDesk()
      if (animal.desk) animal.desk.user = animal
    }
    const seat = animal.desk ? animal.desk.position.clone().add(new THREE.Vector3(-SEAT, 0, 0)) : null
    if (!seat) {
      // Every desk is taken: run laps inside the office.
      const angle = time * 0.8 + animal.phase
      walkTo(animal, new THREE.Vector3(23 + Math.cos(angle) * 6, 0, Math.sin(angle) * 10), 8, dt)
    } else if (walkTo(animal, seat, 8, dt)) {
      turnTo(animal, 0, dt)  // face the screen
      animal.legs.slice(0, 2).forEach((leg, index) => (leg.rotation.z = 0.9 + Math.sin(time * 18 + index * 2) * 0.35))
      position.y = Math.abs(Math.sin(time * 9)) * 0.05
      if (Math.floor(time * 2) !== animal.lastScreen) {
        animal.lastScreen = Math.floor(time * 2)
        drawScreen(animal.desk, SCREEN_TEXT[(animal.lastScreen + DESKS.indexOf(animal.desk.position)) % SCREEN_TEXT.length], animal.color)
      }
    } else {
      drawScreen(animal.desk, "boot" + ".".repeat(Math.floor(time * 4) % 4), animal.color)
    }
    setText(animal.speech, WORK_SAY[Math.floor(time * 0.7 + animal.phase) % WORK_SAY.length])
    return
  }
  // Idle: stroll around the park, stopping now and then.
  freeDesk(animal)
  if (animal.rest > 0) {
    animal.rest -= dt
    still(animal)
    if (animal.rest <= 0) setText(animal.speech, "")
    return
  }
  setText(animal.speech, "")
  if (walkTo(animal, animal.target, 2.5, dt)) {
    animal.target = parkSpot()
    animal.rest = 1 + Math.random() * 4
  }
}

// --- main loop --------------------------------------------------------------------

buildPark()
const sign = buildOffice()
connect()

// Frames per second, for tuning: shown with ?fps and readable as window.parkFps.
const fpsLabel = new URLSearchParams(location.search).has("fps") && document.getElementById("title")
let frames = 0, fpsSince = performance.now()
function countFrame() {
  frames++
  const now = performance.now()
  if (now - fpsSince >= 1000) {
    window.parkFps = Math.round((frames * 1000) / (now - fpsSince))
    if (fpsLabel) fpsLabel.textContent = `Agent Park 3D · ${window.parkFps} fps · ${renderer.info.render.calls} draw calls`
    frames = 0
    fpsSince = now
  }
}

const clock = new THREE.Clock()
let lastFrame = 0
renderer.setAnimationLoop((now) => {
  if (FPS_CAP && now - lastFrame < 1000 / FPS_CAP - 2) return
  lastFrame = now
  countFrame()
  if (frames % SHADOW_EVERY === 0) renderer.shadowMap.needsUpdate = true
  const dt = Math.min(clock.getDelta(), 0.1), time = clock.elapsedTime
  for (const animal of [...animals.values()]) update(animal, dt, time)
  if (lastState && performance.now() - lastState > STALE) message.textContent = "Data dari park_state.py berhenti..."
  controls.update()
  renderer.render(scene, camera)
  labels.render(scene, camera)
})

addEventListener("resize", () => {
  camera.aspect = innerWidth / innerHeight
  camera.updateProjectionMatrix()
  renderer.setSize(innerWidth, innerHeight)
  labels.setSize(innerWidth, innerHeight)
})
