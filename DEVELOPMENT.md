# Workflow Harian Tim Siskamling Pasar (Panduan Development & Kolaborasi)

Panduan ini mengatur standar teknis, alur pengerjaan fitur, pengujian kuantitatif, dan tata cara kolaborasi untuk seluruh engineer di project **Siskamling Pasar**.

---

## Standar Project

Project ini dibangun dengan arsitektur **Python 3.10+ (disarankan 3.11 atau 3.12)** murni deterministik (tanpa dependensi LLM untuk scoring), didukung **FastAPI**, bot **Telegram & Discord**, dan **n8n** sebagai mesin orkestrasi otomasi workflow.

### Aturan Environment & Dependensi:
1. **Wajib Menggunakan Virtual Environment (`.venv`)**:
   Jangan pernah menginstall package secara global di laptop/mesin lokal.
   ```bash
   # Pembuatan venv (cukup sekali di awal)
   python -m venv .venv

   # Aktivasi di Windows (PowerShell):
   .venv\Scripts\Activate.ps1

   # Aktivasi di Linux/macOS:
   source .venv/bin/activate
   ```
2. **Sinkronisasi Package**:
   Selalu instal dependensi dari file `requirements.txt`:
   ```bash
   pip install -r requirements.txt
   ```
   Jika menambahkan pustaka baru, pastikan didiskusikan dulu dengan tim (ingat prinsip: *Standard Library first, hindari dependency bloat*), lalu update `requirements.txt`.
3. **Kerahasiaan Environment (`.env`)**:
   - File `.env` **DILARANG KERAS** di-commit ke Git!
   - Salin contoh konfigurasi dari `.env.example`:
     ```bash
     cp .env.example .env
     ```
   - Isi `SECTORS_API_KEY` dan token bot lokal masing-masing.
4. **Folder Data & Cache Lokal**:
   Folder `data/cache/`, `runs/`, dan file `.venv/` adalah aset lokal dan sudah masuk `.gitignore`. Jangan pernah di-force commit ke repository.
5. **Kebijakan Commit & PR (Human Engineer)**:
   Semua pesan commit, judul Pull Request, dan deskripsi review harus rapi, profesional, dan murni ditulis layaknya engineer profesional (tanpa mencantumkan tag/atribusi AI atau bot otomatis).

---

## Langkah A: Update Lokal Main & Sinkronisasi Dependensi

Sebelum mulai membuat fitur baru, endpoint baru, atau formula skoring baru, pastikan repositori lokalmu sinkron dengan kode terbaru dari rekan tim:

```bash
git checkout main
git pull origin main

# Pastikan venv aktif dan dependensi ter-update
pip install -r requirements.txt
```

---

## Langkah B: Buat Branch Fitur Baru

Selalu buat branch baru yang terisolasi dari branch `main`.

```bash
# Untuk fitur baru:
git checkout -b feature/nama-fitur-kalian

# Untuk perbaikan bug:
git checkout -b fix/nama-bug-kalian
```

**Contoh penamaan branch yang baik:**
- `feature/sqri-amihud-liquidity`
- `feature/portfolio-telegram-command`
- `feature/n8n-pipeline-webhook`
- `fix/sectors-api-retry-logic`

---

## Langkah C: Ngoding, Pengujian (TDD), & Commit

Kerjakan kodemu. Terapkan prinsip **Clean Code**: deterministik, modular, dan tangguh terhadap *edge case* bursa (hari libur, suspensi saham, dividen kosong, dsb).

### 1. Jalankan Unit Tests (Wajib Lulus 100%)
Sebelum melakukan commit, **seluruh unit test wajib lulus tanpa error**:

```bash
# Jalankan seluruh test suite
python -m unittest discover -s tests -p "test_*.py"

# Atau jalankan test spesifik yang sedang kamu kerjakan
python tests/test_sqri.py
```

### 2. Format & Kerapian Kode
Pastikan kode mematuhi kaidah PEP 8, tipe data terdefinisi (`type hints`), dan tidak meninggalkan debugging print liar.

### 3. Commit dengan Format Jelas (Conventional Commits)
Gunakan format commit yang terstandar:
```bash
git add .
git commit -m "feat: implement volume z-score anomaly calculation"
```

Prefix commit yang dianjurkan:
- `feat:` Penambahan fitur baru (endpoint, formula, command bot).
- `fix:` Perbaikan bug atau kesalahan kalkulasi.
- `refactor:` Restrukturisasi kode tanpa mengubah fungsionalitas.
- `test:` Penambahan atau perbaikan unit test.
- `docs:` Pembaruan dokumentasi atau panduan.

---

## Langkah D: Push Branch Fitur ke GitHub

Kirim branch pekerjaanmu ke remote repository di GitHub:

```bash
git push origin feature/nama-fitur-kalian
```

---

## Langkah E: Bikin Pull Request (PR) & Code Review

1. Buka [GitHub Siskamling Pasar](https://github.com/diwanparker/siskamling-pasar).
2. Buat **Pull Request (PR)** dari branch fiturmu menuju branch `main`.
3. Tulis ringkasan singkat:
   - Apa yang diubah?
   - Mengapa perubahan ini dibutuhkan?
   - Bukti pengujian (output `unittest` yang lolos).
4. **Peer Review**: Minta rekan tim mereviu kodemu sebelum di-merge. Setelah disetujui (Approved) dan CI/test hijau, branch siap di-merge ke `main`.

---

## Langkah F: Deployment ke Server HermesVPS (Produksi)

Ketika fitur sudah di-merge ke `main`, lakukan deployment ke server produksi HermesVPS:

```bash
# Masuk ke server dan pull kode terbaru
cd /home/diwan/siskamling-pasar
git pull origin main

# Jalankan test verifikasi di server
python3 -m unittest discover -s tests -p "test_*.py"

# Restart layanan aplikasi di PM2
pm2 restart siskamling-api siskamling-bot --update-env
pm2 save

# Periksa status layanan
pm2 status
```

Jika kamu mengubah alur n8n di file `workflows/*.json`, pastikan perubahannya juga disinkronkan ke canvas n8n di `http://127.0.0.1:5678` (atau lewat tunnel Cloudflare).

---

## Golden Rules Anti-Konflik untuk Tim Siskamling Pasar

### 1. Komunikasi Arsitektur Inti
Hindari merombak file pondasi tanpa koordinasi dengan rekan tim:
- Formula risiko di `siskamling/score.py`.
- Client HTTP di `siskamling/sectors.py`.
- Skema endpoint FastAPI di `siskamling/api.py`.
- Routing perintah bot di `siskamling/platforms/`.
Jika ingin merestrukturisasi modul-modul ini, komunikasikan terlebih dahulu di grup chat tim.

### 2. Sering Sinkronisasi dari `main` (Alur Git Stash Anti-Bentrokan)
Jika pengerjaan fiturmu butuh waktu beberapa hari, setiap pagi tarik update terbaru dari `main` ke branch fiturmu agar selisih kodenya tidak menumpuk.

Jika kamu sedang coding dan belum siap commit, gunakan alur **Stash**:

```bash
# 1. Simpan kodemu yang belum selesai ke penyimpanan sementara
git stash

# 2. Pindah ke branch utama
git checkout main

# 3. Tarik update terbaru dari GitHub
git pull origin main

# 4. Kembali ke branch fiturmu
git checkout feature/nama-fitur-kalian

# 5. Gabungkan perubahan main ke branch fiturmu
git merge main

# 6. Keluarkan kembali kodemu dari penyimpanan sementara
git stash pop
```

> **⚠️ Peringatan saat `git stash pop`:**  
> Jika kode dari `main` mengubah file yang persis sama dengan yang sedang kamu ubah, Git akan menandai *Merge Conflict*. Buka file tersebut di VS Code, pilih baris kode yang benar (*Accept Current Change* / *Accept Incoming Change*), pastikan unit test tetap lulus, lalu lanjutkan pekerjaanmu.

### 3. DILARANG Force Push (`git push --force`)
Jangan pernah melakukan `git push --force` ke branch `main` atau branch bersama. Force push bisa menghapus commit rekan tim yang sudah ada di remote.

### 4. Siklus Workflow n8n: Single Source of Truth
- Seluruh workflow n8n wajib diekspor dan disimpan ke folder `workflows/` (misalnya `workflows/siskamling_patrol_workflow.json`).
- Jangan hanya mengubah workflow langsung di browser n8n tanpa mencatat versinya di Git, agar konfigurasi server tidak hilang jika terjadi reset database.

### 5. Perlakukan Kredensial dengan Ketat
- Jangan pernah menuliskan API Key Sectors atau token bot Telegram/Discord langsung di dalam kode (*hardcode*).
- Selalu panggil via `os.environ.get(...)`.
- Semua nilai rahasia hanya boleh disimpan di file `.env`.
