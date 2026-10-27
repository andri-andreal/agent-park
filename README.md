# Agent Park

Agen AI yang sedang kamu jalankan (Claude Code, Codex, OpenCode, Kiro, Pi, ...)
hidup sebagai hewan di sebuah taman: masuk kantor saat bekerja, melompat saat
butuh persetujuanmu, dan bermain saat menganggur. Tersedia sebagai screensaver
terminal dan sebagai aplikasi 3D.

![Agent Park di terminal: Claude dan Codex bekerja di meja masing-masing, OpenCode minta izin, Kiro dan Pi bermain di taman](docs/terminal.png)

Secara bawaan, taman hanya dihuni hewan milik sesi Claude Code, Codex, dan OpenCode
yang sedang berjalan (lihat **Kucing AI** di bawah), anak-anaknya untuk subagent, dan
monster dari proses berat. Kalau belum ada sesi, taman kosong dengan tulisan
`Taman sepi...`. Jalankan dengan `--semua` untuk ikut memunculkan binatang
liar di bawah ini.

Kucing, anjing, kelinci, bebek, dan tikus ASCII dengan kelakuan acak.
Ada yang jalan santai, tidur, membersihkan bulu, melompat, atau lari mendadak.
Kalau bertemu, mereka bisa saling sapa, kejar-kejaran, atau berantem kartun
dengan awan debu dan tulisan POW/BONK, lalu kabur ke arah berlawanan.

Binatang baru sesekali masuk dari tepi layar; sebagian hanya numpang lewat
lalu keluar lagi. Jumlah binatang menyesuaikan luas layar (maksimal delapan).
Berjalan di Linux/macOS dengan Python 3, tanpa paket tambahan.

Ada empat tempat yang berganti otomatis setiap 35 detik:

- **Taman**: pohon, bangku, rumput, dan awan bergerak.
- **Hutan**: deretan pohon dan kunang-kunang.
- **Pantai**: pohon kelapa, matahari, pasir, dan ombak bergerak.
- **Desa**: rumah-rumah dan jalan.

Binatang berjalan di area tanah di bawah pemandangan. Pindah lokasi tidak
menghapus binatang atau menghentikan interaksi. Saat dijeda, hitung mundur
pergantian tempat juga berhenti.

Monster menyerang kalau ada proses berat yang baru muncul di komputer! Semua hewan, termasuk yang tidur dan yang numpang
lewat, menghentikan aktivitas untuk berkumpul, menangkis serangan dengan
perisai, lalu kompak menyerang balik. Monster selalu kalah dan kabur;
hewan-hewan merayakan kemenangan dengan lompatan dan konfeti sebelum kembali
beraktivitas. Tidak ada hewan yang terluka.

Monster bukan muncul acak. Monster adalah proses yang dimulai setelah
screensaver dibuka (termasuk shell yang `exec` program lain), lalu memakai CPU
rata-rata minimal 90% satu core selama 3 detik atau RAM minimal 1 GB. Contohnya
`cargo build` atau test yang dijalankan agen. Nama monster diambil dari nama
prosesnya, misalnya "Monster cargo (CPU 180%)". Proses yang sudah berjalan
sebelum screensaver dibuka, serta agen AI itu sendiri, tidak pernah jadi
monster. Satu proses hanya menyerang sekali, dan setelah pertempuran ada jeda
30 detik. Batasnya bisa diubah di `MONSTER_CPU`, `MONSTER_RSS`, dan
`RAID_COOLDOWN`. Tekan `r` untuk memicu serangan secara manual. Satu kejadian
berlangsung sekitar 14 detik. Pergantian lokasi dan kedatangan hewan baru
menunggu sampai pertempuran berakhir; tombol jeda tetap berfungsi.

Panel sistem: di pojok kanan atas ada kotak kecil ala btop berisi CPU, RAM,
swap (kalau ada), load average, dan grafik CPU 24 detik terakhir. Di
sebelahnya duduk kucing penjaga. Kalau CPU di atas 60%, kucingnya mulai
khawatir (`CPU naik nih...`). Kalau CPU di atas 85% atau RAM di atas 90%,
kucingnya panik, gemetar, dan berteriak `AWAS! CPU 93%!`. Panel hanya muncul
di Linux pada terminal minimal 64x20.

Kucing AI: setiap sesi **Claude Code**, **Codex CLI**, atau **OpenCode** yang
sedang berjalan mendapat hewan sendiri: kucing oranye `[Claude]`, anjing biru
`[Codex]`, atau kelinci ungu muda `[OpenCode]`. Untuk mudahnya, semuanya
disebut "kucing AI" di bawah. Provider atau model yang dipakai tidak
berpengaruh: OpenCode dengan DeepSeek, Gemini, atau model lokal tetap jadi
kelinci `[OpenCode]`.
Sesi kedua dan berikutnya diberi nomor, misalnya `[Claude 2]`. Status dibaca
dari `/proc` setiap detik berdasarkan pemakaian CPU rata-rata 3 detik terakhir:
kalau sesi sedang bekerja, kucingnya lari ke **Markas AI**, area berpagar di
sisi kanan tanah yang berisi deretan komputer. Setiap kucing mendapat meja
sendiri, duduk menghadap komputernya, lalu mengetik heboh sambil berteriak
`tik tak tuk!`, `ngoding!!`, dan sejenisnya, sementara layar komputernya
menampilkan `>_ make`, progress bar, dan lain-lain. Komputer yang kosong
menampilkan `zz`. Kalau semua meja terisi, kucing sisanya lari-lari di dalam
markas. Papan di atas
markas menunjukkan berapa yang sedang kerja. Begitu sesi berhenti, kucingnya
keluar dari markas dan bermain di taman seperti hewan lain (tetapi tidak ikut
berantem). Hewan biasa tidak masuk ke markas. Markas hanya muncul kalau ada
kucing AI dan terminal minimal 72 kolom; di layar sempit kucing bekerja di
seluruh taman. Begitu sesi ditutup, kucingnya pamit dan
berjalan keluar layar. Kucing AI tidak ikut berantem, tetapi tetap ikut
melawan monster. Fitur ini hanya berjalan di Linux.

Tanpa pengaturan tambahan, status kerja hanya perkiraan dari CPU. Supaya
akurat, pasang hook yang memanggil `agent_hook.py`. Script ini menulis status
sesi ke `$XDG_RUNTIME_DIR/agent-park/<pid>.json`, lalu screensaver
membacanya:

- `work`: kamu mengirim prompt atau agen sedang memakai tool. Kucing duduk di komputernya di markas dan mengetik.
- `wait`: agen meminta izin. Kucing melompat-lompat dengan label
  `butuh kamu!`.
- `idle`: giliran selesai atau dihentikan. Kucing keluar dari markas dan bermain di taman.

Hook juga mencatat model yang dipakai sesi, lalu model itu tampil di label
hewan, misalnya `[Claude | opus-5-5]`. Sumbernya:

| Agen | Sumber model |
| --- | --- |
| Claude Code | balasan terakhir di transkrip (`transcript_path` dari hook) |
| Codex | `~/.codex/sessions/.../rollout-*-<session>.jsonl` |
| Kiro | `~/.kiro/sessions/cli/<session>.jsonl`; mode Auto hanya tercatat `auto` |
| OpenCode | dikirim plugin; cadangannya kolom `session_v2.model` di database OpenCode (dibuka read-only) |
| Pi | `ctx.model` dari extension, termasuk saat `/model` atau Ctrl+P |

Model baru muncul setelah hook pertama sesi itu berjalan. Agen tanpa hook
tidak menampilkan model.

Kucing AI tidak masuk biasa-biasa saja. Cara masuknya dipilih acak: jatuh
sebagai **meteor** (KABOOM!), diturunkan **UFO** pakai sinar, keluar dari
**portal**, **terjun payung**, atau **ter-teleport** dari karakter acak.
Kalau monster menyerang saat kucing sedang mendarat, kucing langsung ikut
bertahan. Anak subagent muncul dengan efek "POP!" setelah induknya
mendarat.

Subagent muncul sebagai **anak** dari hewan induknya (anak kucing, anak
anjing, atau anak kelinci) berlabel jenisnya (misalnya
`[Explore]`). Anak-anak ini berlarian mengitari induknya dan pergi saat
subagent selesai. Paling banyak 4 anak per induk. Anak yang
event `SubagentStop`-nya tidak pernah datang dihapus setelah 30 menit.

Claude Code (`~/.claude/settings.json`), satu entri per event
`UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`,
`SubagentStart`, `SubagentStop`, `PermissionRequest`, `Notification`, `Stop`,
`StopFailure`, `SessionStart`, `SessionEnd`:

```json
{"hooks": {"Stop": [{"hooks": [{"type": "command", "timeout": 5,
  "command": "python3 /path/ke/screensaver/agent_hook.py claude"}]}]}}
```

Codex CLI (`~/.codex/hooks.json`) memakai format yang sama dengan argumen
`codex`, untuk event `UserPromptSubmit`, `PreToolUse`, `PostToolUse`,
`SubagentStart`, `SubagentStop`, `PermissionRequest`, `Stop`, `Interrupt`,
`SessionStart`, `SessionEnd`. Setujui hook-nya sekali lewat `/hooks` di Codex.

Codex menjalankan hook dari satu proses latar (`codex app-server`) yang
melayani semua jendela Codex, jadi tidak diketahui jendela mana yang punya
sesi tertentu. Karena itu status Codex disimpan per sesi
(`codex-<session_id>.json`), dan kucing Codex diambil dari sesi terbaru
sebanyak jendela Codex yang sedang terbuka. Jendela yang belum mengirim event
memakai perkiraan CPU.

Kalau profil [ccx](../ccx) memakai router (`ccx-router`), kotak **router ccx**
muncul di kiri atas. Isinya nama profil, port lokal, host upstream (tanpa path
atau kredensial), lama berjalan, dan kucing Claude yang memakainya. Panah
`>-->` bergerak saat router atau kucingnya sedang bekerja; kalau tidak, tertulis
`diam` dan jumlah koneksi terbuka. Paling banyak tiga router ditampilkan,
sisanya diringkas menjadi `+N lagi`. Router tidak pernah jadi monster.

OpenCode tidak punya hook berupa perintah, jadi statusnya dikirim lewat plugin
`opencode_plugin.js`. Plugin ini mengubah event sesi OpenCode (sibuk, minta
izin atau bertanya, selesai) menjadi event ala Claude, lalu memanggil
`agent_hook.py opencode`. Subagent OpenCode (misalnya `@explore`) muncul sebagai
anak kelinci. Plugin ini mendukung OpenCode 1.x dan 2.x. Pasang dengan symlink:

```sh
mkdir -p ~/.config/opencode/plugins
ln -s "$PWD/opencode_plugin.js" ~/.config/opencode/plugins/agent-park.js
opencode service restart   # OpenCode 2.x; di 1.x cukup buka ulang OpenCode
```

Mulai OpenCode 2.x, semua jendela dilayani satu proses latar
(`opencode serve --service`), dan plugin berjalan di situ. Proses latar itu
sendiri tidak dianggap sesi. Seperti Codex, status disimpan per sesi
(`opencode-<session_id>.json`) dan dibagikan ke jendela OpenCode yang terbuka.

Daftar agen yang dikenali:

| Agen | Proses | Hewan | Status akurat |
| --- | --- | --- | --- |
| Claude Code | `claude` | kucing oranye | hook (di atas) |
| Codex CLI | `codex` | anjing biru | hook (di atas) |
| OpenCode | `opencode` | kelinci ungu muda | plugin (di atas) |
| Kiro CLI | `kiro-cli`, `kiro-cli-chat` | tikus ungu | hook (di bawah) |
| Aider | `aider` | tikus hijau | perkiraan CPU |
| Goose | `goose` | bebek kuning | perkiraan CPU |
| Crush | `crush` | kucing merah muda | perkiraan CPU |
| Amp | `amp` | anjing merah | perkiraan CPU |
| Pi | `pi` | bebek biru muda | extension (di bawah) |
| Strix | `strix` | anjing merah tua | perkiraan CPU |

Pi berjalan di atas Node tetapi mengganti nama prosesnya menjadi `pi`, jadi
tetap terdeteksi. Statusnya dikirim lewat extension `pi_extension.ts`: mulai
dan selesai menjawab prompt (termasuk Esc), serta keluar. Pi tidak punya
prompt izin bawaan atau subagent, jadi tidak ada `butuh kamu!` maupun anak
bebek. Pasang dengan symlink, lalu buka ulang Pi:

```sh
mkdir -p ~/.pi/agent/extensions
ln -s "$PWD/pi_extension.ts" ~/.pi/agent/extensions/agent-park.ts
```

Kiro CLI hanya mendukung hook di agen kustom. Cara paling aman adalah menyalin
agen bawaan supaya semua tool tetap aktif. Setelah itu tambahkan bagian `hooks`
di bawah ke `~/.kiro/agents/agent-park.json`, periksa, lalu jadikan default:

```sh
EDITOR=true kiro-cli agent create agent-park --from kiro_default
kiro-cli agent validate --path ~/.kiro/agents/agent-park.json
kiro-cli agent set-default agent-park
```

Agen yang hanya berisi `hooks` bisa kehilangan akses ke tool. Nama event Kiro memakai camelCase,
dan `agent_hook.py` menerimanya apa adanya. Kiro hanya punya lima event ini dan
tidak punya event saat meminta izin, jadi hewannya tidak bisa menampilkan
`butuh kamu!`.

```json
{"hooks": {
  "agentSpawn": [{"command": "python3 /path/ke/screensaver/agent_hook.py kiro-cli"}],
  "userPromptSubmit": [{"command": "python3 /path/ke/screensaver/agent_hook.py kiro-cli"}],
  "preToolUse": [{"command": "python3 /path/ke/screensaver/agent_hook.py kiro-cli"}],
  "postToolUse": [{"command": "python3 /path/ke/screensaver/agent_hook.py kiro-cli"}],
  "stop": [{"command": "python3 /path/ke/screensaver/agent_hook.py kiro-cli"}]
}}
```

Agen lain bisa ditambahkan di tabel `AGENTS` di `screensaver.py` (nama proses,
nama, jenis hewan, warna). Hewannya juga bisa diganti di tabel itu, misalnya
`"bebek"` atau `"tikus"`. Agen yang terdeteksi tetapi tidak punya hook memakai
perkiraan CPU. Syaratnya, nama prosesnya di `/proc/<pid>/comm` harus khas.
Agen yang berjalan sebagai `node` biasa tidak bisa dibedakan dengan cara ini.

Claude tidak mengirim event saat kamu menekan Esc. Karena itu, status `work`
yang lebih tua dari 90 detik kembali dibaca dari CPU.

Jalankan dari folder proyek:

```sh
python3 screensaver.py          # hanya kucing AI
python3 screensaver.py --semua  # plus binatang liar
```

Aktifkan fullscreen dari aplikasi terminal kamu (biasanya **F11** di Linux).
Animasi otomatis mengikuti ukuran terminal, termasuk setelah resize.

| Tombol | Fungsi |
| --- | --- |
| `q` / `Esc` | Keluar |
| `Spasi` | Jeda / lanjut |
| `+` / `-` | Tambah / kurangi kecepatan |
| `n` | Datangkan binatang yang numpang lewat, kalau layar belum penuh (hanya dengan `--semua`) |
| `l` | Pindah ke lokasi berikutnya |
| `r` | Picu serangan monster; semua hewan bekerja sama sampai menang |
| `a` | Aktifkan / matikan pergantian lokasi otomatis (menetap di tempat sekarang) |
| `s` | Tampilkan / sembunyikan panel sistem |
| `Ctrl+C` | Keluar |

Saat keluar, tampilan terminal dan kursor dikembalikan seperti semula.
Ini animasi yang dijalankan manual; belum terhubung ke pengaturan screensaver sistem.

## Agent Park 3D

![Agent Park 3D: Pi dan OpenCode bekerja di kantor, Claude minta izin bersama anak subagent Explore, Codex dan Kiro bermain di taman](docs/park3d.png)

`park3d/` berisi versi 3D dari taman ini sebagai aplikasi desktop
([Tauri](https://tauri.app) dengan Three.js). Terminal tetap bisa dipakai seperti
biasa. Logika deteksi agen tetap ada di Python: aplikasi menjalankan
`park_state.py`, yang mencetak status taman sebagai satu baris JSON per detik
(agen, subagent, CPU/RAM, monster), lalu dunia 3D menggerakkan hewannya sendiri
berdasarkan status itu. Agen baru cukup ditambahkan di tabel `AGENTS`, dan kedua
tampilan langsung kebagian.

```sh
cd park3d
pnpm install
pnpm tauri dev                 # jalankan sambil mengembangkan
pnpm tauri build --no-bundle   # binary: src-tauri/target/release/park3d
```

Opsi tampilan, sebagai argumen aplikasi (`park3d --low --fps`) atau di URL
browser (`?low&fps`):

| Opsi | Fungsi |
| --- | --- |
| `--low` | Tanpa bayangan dan antialiasing, resolusi 1×. Paling ringan |
| `--fps` | Tampilkan FPS dan jumlah draw call di pojok kiri atas |
| `--cap=N` | Batas FPS (bawaan 30; `--cap=0` tanpa batas) |
| `--smooth` | 60 FPS, sama dengan `--cap=0` |

Butuh Rust, Node, pnpm, dan `webkit2gtk-4.1`. `python3 park_state.py --once`
menampilkan satu potongan status, dan `pnpm dev` lalu membuka
`http://localhost:1420/?demo` menampilkan dunia 3D dengan agen contoh di browser
biasa. Di Wayland, aplikasi menyetel `WEBKIT_DISABLE_DMABUF_RENDERER=1` supaya
WebGL tidak hitam. Lokasi script status bisa diganti lewat `PARK_STATE`.

Uji simulasi interaksi, binatang lewat, dan resize dengan:

```sh
python3 -m unittest -v
```
