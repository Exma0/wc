#!/usr/bin/env python3
"""
⛏️  Minecraft Distributed Hub Engine  —  Tek Dosya (MAX OPTIMIZATION)
═══════════════════════════════════════════════════════════
  • Tam BungeeCord Mimarisi (Hot-Swap / Kesintisiz Gecis)
  • Otomatik Olceklendirme (Auto-Scaling): GM1, GM2, GM3...
  • MySQL Veritabani: Envanter, Konum, Can ve Sunucu Durumu
  • Teleport Yuzugu (GUI) & Global Chat
"""

import asyncio, json, os, pathlib, struct, sys
import threading, zlib, time, http.server, urllib.request, urllib.parse
import subprocess, glob, uuid as _uuid_mod
from collections import deque
import datetime

try:
    import aiomysql
    import pymysql
except ImportError:
    print("[SISTEM] 'aiomysql' veya 'pymysql' bulunamadi! 'pip install aiomysql pymysql' komutunu calistirin.")
    sys.exit(1)

# ══════════════════════════════════════════════════════════
#  SİSTEM DEĞİŞKENLERİ VE VERİTABANI BAĞLANTISI
# ══════════════════════════════════════════════════════════

MODE          = os.environ.get("ENGINE_MODE", "gameserver")
if "wc-yccy" in os.environ.get("RENDER_EXTERNAL_HOSTNAME", ""):
    MODE = "all"

HTTP_PORT     = int(os.environ.get("PORT", 8080))
MC_PORT       = int(os.environ.get("MC_PORT", 25565))
CUBERITE_PORT = 25566 if MODE == "all" else MC_PORT

DATA_DIR      = os.environ.get("DATA_DIR", "/data")
SERVER_DIR    = os.environ.get("SERVER_DIR", "/server")
BORE_FILE     = "/tmp/bore_address.txt"

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_USER = os.environ.get("DB_USER", "root")
DB_PASS = os.environ.get("DB_PASS", "")
DB_NAME = os.environ.get("DB_NAME", "minecraft_db")

db_pool = None
_current_bore_addr = None
_active_players = []

async def init_db():
    global db_pool
    try:
        db_pool = await aiomysql.create_pool(
            host=DB_HOST, port=3306, user=DB_USER, password=DB_PASS,
            db=DB_NAME, autocommit=True, minsize=1, maxsize=15
        )
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS servers (
                        label VARCHAR(20) PRIMARY KEY,
                        host VARCHAR(100),
                        port INT,
                        players INT DEFAULT 0,
                        last_seen INT
                    )
                """)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS players (
                        username VARCHAR(50) PRIMARY KEY,
                        uuid VARCHAR(50),
                        last_server VARCHAR(20),
                        inventory TEXT,
                        pos_x FLOAT DEFAULT 0,
                        pos_y FLOAT DEFAULT 5,
                        pos_z FLOAT DEFAULT 0,
                        health FLOAT DEFAULT 20
                    )
                """)
        print("[DB] MySQL Baglantisi Basarili ve Tablolar Hazir.")
    except Exception as e:
        print(f"[DB] KRITIK HATA: MySQL Baglantisi Kurulamadi -> {e}")

# ══════════════════════════════════════════════════════════
#  CUBERITE AYARLARI VE LUA EKLENTİSİ (TELEPORT YÜZÜĞÜ)
# ══════════════════════════════════════════════════════════

SETTINGS_INI = f"""
[Authentication]
Authenticate=0
OnlineMode=0
ServerID=WCHubEngine

[Plugins]
Plugin=WCHub

[Server]
Description=Minecraft Distributed Hub
MaxPlayers=100
Port={CUBERITE_PORT}
Ports={CUBERITE_PORT}
NetworkCompressionThreshold=-1
"""

WORLD_INI = """
[General]
Gamemode=0
WorldType=FLAT
AllowFlight=1
[SpawnPosition]
MaxViewDistance=4 
X=0
Y=5
Z=0
"""

# LUA Eklentisi: Yuzuk verme, GUI acma, Sunucu Listesi Cekme, Konum Kaydetme
PLUGIN_MAIN = """
local ProxyURL = "http://127.0.0.1:8080"
if os.getenv("PROXY_URL") then ProxyURL = os.getenv("PROXY_URL") end

-- Basit Split fonksiyonu (Cuberite'da JSON olmadigi icin ozel format kullaniyoruz)
local function Split(str, sep)
    local res = {}
    for w in string.gmatch(str, "([^"..sep.."]+)") do table.insert(res, w) end
    return res
end

function Initialize(Plugin)
    Plugin:SetName("WCHub")
    Plugin:SetVersion(3)
    cPluginManager:AddHook(cPluginManager.HOOK_PLAYER_JOINED, OnPlayerJoined)
    cPluginManager:AddHook(cPluginManager.HOOK_PLAYER_DESTROYED, OnPlayerDestroyed)
    cPluginManager:AddHook(cPluginManager.HOOK_PLAYER_RIGHT_CLICK, OnRightClick)
    
    cRoot:Get():GetDefaultWorld():ScheduleTask(200, PeriodicSave)
    LOG("[HUB] WCHub aktif! Yuzuk sistemi devrede.")
    return true
end

function GiveRing(Player)
    local inv = Player:GetInventory()
    local hasRing = false
    for i=0, 35 do
        local item = inv:GetSlot(i)
        if item.m_ItemType == E_ITEM_COMPASS then hasRing = true break end
    end
    if not hasRing then
        local ring = cItem(E_ITEM_COMPASS, 1)
        ring.m_CustomName = "§eSunucu Secici §7(Sag Tik)"
        inv:AddItem(ring)
    end
end

function OnPlayerJoined(Player)
    GiveRing(Player)
    Player:SendMessageSuccess("Merkezi Hub'a Hos Geldin!")
end

function OnPlayerDestroyed(Player)
    local name = Player:GetName()
    local x, y, z = Player:GetPosX(), Player:GetPosY(), Player:GetPosZ()
    local hp = Player:GetHealth()
    local payload = string.format('{"x":%f,"y":%f,"z":%f,"hp":%f}', x, y, z, hp)
    
    local req = cNetwork::CreateRequest(ProxyURL .. "/api/player?name=" .. name)
    req:SetMethod("POST")
    cNetwork:PostData(req, payload, function() end)
end

function PeriodicSave(World)
    World:ForEachPlayer(function(Player)
        local name = Player:GetName()
        local x, y, z = Player:GetPosX(), Player:GetPosY(), Player:GetPosZ()
        local hp = Player:GetHealth()
        local payload = string.format('{"x":%f,"y":%f,"z":%f,"hp":%f}', x, y, z, hp)
        
        local req = cNetwork::CreateRequest(ProxyURL .. "/api/player?name=" .. name)
        req:SetMethod("POST")
        cNetwork:PostData(req, payload, function() end)
    end)
    World:ScheduleTask(200, PeriodicSave)
end

function OnRightClick(Player, BlockX, BlockY, BlockZ, BlockFace, CursorX, CursorY, CursorZ)
    local EquippedItem = Player:GetEquippedItem()
    if EquippedItem.m_ItemType == E_ITEM_COMPASS then
        -- HTTP uzerinden anlik sunucu verisini cekiyoruz. Format: GM1:10;GM2:5;GM3:0
        cNetwork:Get(ProxyURL .. "/api/servers", function(Body, Data)
            if Body and Body ~= "" then
                Player:SendMessageInfo("Aktif Sunucular Listeleniyor...")
                local servers = Split(Body, ";")
                for i, srv in ipairs(servers) do
                    local parts = Split(srv, ":")
                    if #parts == 2 then
                        local label = parts[1]
                        local count = parts[2]
                        -- Tıklanabilir Text (Cuberite GUI hatalarina karsi en guvenli yontem)
                        Player:SendMessage(cCompositeChat():AddTextPart("§8[§b" .. label .. "§8] §7- Aktif: §e" .. count .. " oyuncu ")
                            :AddRunCommandPart("§a[BAGLAN]", "/wc_transfer " .. label))
                    end
                end
            else
                Player:SendMessageFailure("Sunuculara ulasilamadi.")
            end
        end)
    end
    return false
end
"""

def write_configs(server_dir=SERVER_DIR):
    files = {
        f"{server_dir}/settings.ini": SETTINGS_INI.strip(),
        f"{server_dir}/world/world.ini": WORLD_INI.strip(),
        f"{server_dir}/Plugins/WCHub/Info.lua": 'g_PluginInfo = {Name="WCHub", Version="3"}',
        f"{server_dir}/Plugins/WCHub/main.lua": PLUGIN_MAIN.strip(),
    }
    for path, content in files.items():
        try:
            pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
            pathlib.Path(path).write_text(content + "\n", encoding="utf-8")
        except Exception: pass

# ══════════════════════════════════════════════════════════
#  PROTOKOL & PAKET İŞLEME
# ══════════════════════════════════════════════════════════

def vi_enc(v):
    r = bytearray()
    while True:
        b = v & 0x7F; v >>= 7
        if v: b |= 0x80
        r.append(b)
        if not v: break
    return bytes(r)

def vi_dec(data, pos=0):
    r = shift = 0
    while True:
        b = data[pos]; pos += 1
        r |= (b & 0x7F) << shift
        if not (b & 0x80): return r, pos
        shift += 7

async def vi_rd(reader):
    r = shift = 0
    while True:
        b = (await reader.readexactly(1))[0]
        r |= (b & 0x7F) << shift
        if not (b & 0x80): return r
        shift += 7

async def pkt_read(reader, comp=-1):
    length = await vi_rd(reader)
    raw = await reader.readexactly(length)
    if comp < 0:
        pid, pos = vi_dec(raw)
        return pid, raw[pos:], vi_enc(length) + raw
    data_len, pos = vi_dec(raw)
    inner = raw[pos:]
    if data_len == 0:
        pid, p2 = vi_dec(inner)
        return pid, inner[p2:], vi_enc(length) + raw
    dec = zlib.decompress(inner)
    pid, p2 = vi_dec(dec)
    return pid, dec[p2:], vi_enc(length) + raw

def pkt_make(pid, payload, comp=-1):
    data = vi_enc(pid) + payload
    if comp < 0: return vi_enc(len(data)) + data
    if len(data) < comp:
        inner = vi_enc(0) + data
        return vi_enc(len(inner)) + inner
    c = zlib.compress(data)
    inner = vi_enc(len(data)) + c
    return vi_enc(len(inner)) + inner

def mc_str_enc(s):
    b = s.encode("utf-8")
    return vi_enc(len(b)) + b

def mc_str_dec(data, pos=0):
    n, pos = vi_dec(data, pos)
    return data[pos:pos+n].decode("utf-8", errors="replace"), pos+n

# ══════════════════════════════════════════════════════════
#  PROXY: YÜK DENGELEME VE BUNGEECORD HOT-SWAP
# ══════════════════════════════════════════════════════════

class PlayerConn:
    def __init__(self, cr, cw):
        self.client_r = cr
        self.client_w = cw
        self.server_r = None
        self.server_w = None
        self.comp = -1
        self.username = "?"
        self.current_label = ""
        self.play_state = False

    async def get_target_server(self, requested_label=None):
        async with db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                if requested_label:
                    await cur.execute("SELECT * FROM servers WHERE label=%s", (requested_label,))
                    return await cur.fetchone()
                
                # Load Balancing: Onceki sunucu
                await cur.execute("SELECT last_server FROM players WHERE username=%s", (self.username,))
                p_row = await cur.fetchone()
                if p_row and p_row['last_server']:
                    await cur.execute("SELECT * FROM servers WHERE label=%s", (p_row['last_server'],))
                    s_row = await cur.fetchone()
                    if s_row and (int(time.time()) - s_row['last_seen']) < 60:
                        return s_row
                
                # En az oyuncuya sahip aktif sunucu
                await cur.execute("SELECT * FROM servers WHERE players < 100 AND (UNIX_TIMESTAMP() - last_seen) < 60 ORDER BY players ASC LIMIT 1")
                return await cur.fetchone()

    async def connect_backend(self, host, port):
        if self.server_w: self.server_w.close()
        self.server_r, self.server_w = await asyncio.open_connection(host, port, limit=2**20)

    # Bungee Tipi Sunucu Degisimi (Dimension Switch Trick)
    async def hot_swap(self, target_label):
        if self.current_label == target_label: return
        srv = await self.get_target_server(target_label)
        
        if not srv:
            msg = json.dumps({"text": f"{target_label} bulunamadi veya kapali!", "color": "red"})
            self.client_w.write(pkt_make(0x02, mc_str_enc(msg) + bytes([0]), self.comp))
            return

        self.play_state = False
        await self.connect_backend(srv['host'], srv['port'])
        
        # Sahte Handshake ve Login gonderimi (Proxy icinden sunucuya baglanma)
        hs = vi_enc(47) + mc_str_enc(srv['host']) + struct.pack(">H", srv['port']) + vi_enc(2)
        self.server_w.write(pkt_make(0x00, hs, -1))
        self.server_w.write(pkt_make(0x00, mc_str_enc(self.username), -1))
        await self.server_w.drain()
        
        # Sunucudan yaniti bekle ve istemciyi kandir
        while True:
            pid, payload, raw = await pkt_read(self.server_r, self.comp)
            if pid == 0x01: # Join Game paketi yakalandi
                dim = payload[4]
                # Minecraft istemcisini yenilemek icin "Boyut Degistirme" (Respawn) paketleri atiyoruz
                respawn_fake = struct.pack(">i", -1 if dim == 0 else 0) + payload[5:8] + mc_str_enc("default")
                respawn_real = struct.pack(">i", dim) + payload[5:8] + mc_str_enc("default")
                
                self.client_w.write(pkt_make(0x07, respawn_fake, self.comp))
                self.client_w.write(pkt_make(0x07, respawn_real, self.comp))
                
                # Konum paketi yollayarak oyun ekranini tazelet
                pos = struct.pack(">dddff", 0.0, 5.0, 0.0, 0.0, 0.0) + bytes([0])
                self.client_w.write(pkt_make(0x08, pos, self.comp))
                await self.client_w.drain()
                
                self.current_label = target_label
                self.play_state = True
                
                # Veritabaninda oyuncunun bulundugu sunucuyu guncelle
                async with db_pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute("UPDATE players SET last_server=%s WHERE username=%s", (target_label, self.username))
                break
            
    async def pipe_c2s(self):
        try:
            while True:
                pid, payload, raw = await pkt_read(self.client_r, self.comp)
                
                # CHAT VE KOMUT KONTROLÜ (Global Chat ve Yuzuk Tıklaması)
                if pid == 0x01 and self.play_state: 
                    msg, _ = mc_str_dec(payload)
                    if msg.startswith("/wc_transfer "):
                        target = msg.split(" ")[1]
                        asyncio.ensure_future(self.hot_swap(target))
                        continue
                    elif not msg.startswith("/"):
                        # Global Chat Broadcast (Tum sunuculardaki oyunculara gider)
                        formatted = json.dumps({"text": f"§8[§b{self.current_label}§8] §7{self.username}§f: {msg}"})
                        b_pkt = pkt_make(0x02, mc_str_enc(formatted) + bytes([0]), self.comp)
                        for c in list(_active_players):
                            if c.play_state:
                                try: c.client_w.write(b_pkt)
                                except: pass
                        continue # Orjinal paketi sunucuya yollama (Boylece chat cift gozukmez)

                if self.server_w:
                    self.server_w.write(raw)
                    await self.server_w.drain()
        except: pass

    async def pipe_s2c(self):
        try:
            while True:
                if not self.server_r: await asyncio.sleep(0.1); continue
                pid, payload, raw = await pkt_read(self.server_r, self.comp)
                
                if pid == 0x03 and self.comp < 0:
                    self.comp, _ = vi_dec(payload)
                
                self.client_w.write(raw)
                await self.client_w.drain()
        except: pass

    async def run(self):
        try:
            pid, payload, raw = await pkt_read(self.client_r, -1)
            p=0; _,p=vi_dec(payload,p); _,p=mc_str_dec(payload,p); p+=2; next_state,_=vi_dec(payload,p)
            
            # Sunucu Durum Ekrani (Ping)
            if next_state == 1:
                status_json = json.dumps({
                    "version": {"name": "1.8.x", "protocol": 47},
                    "players": {"max": 1000, "online": len(_active_players), "sample": []},
                    "description": {"text": f"§bWC Hub Agi §8- §e{len(_active_players)} Oyuncu Aktif"}
                })
                self.client_w.write(pkt_make(0x00, mc_str_enc(status_json), -1))
                await self.client_w.drain()
                return

            if next_state == 2:
                pid2, payload2, raw2 = await pkt_read(self.client_r, -1)
                self.username, _ = mc_str_dec(payload2)
                
                srv = await self.get_target_server()
                if not srv:
                    self.client_w.write(pkt_make(0x00, mc_str_enc(json.dumps({"text":"§cSunucu bulunamadi veya hepsi kapali."})), -1))
                    return

                self.current_label = srv['label']
                await self.connect_backend(srv['host'], srv['port'])
                self.server_w.write(raw)
                self.server_w.write(raw2)
                await self.server_w.drain()
                
                _active_players.append(self)
                self.play_state = True
                print(f"[PROXY] {self.username} -> {self.current_label} sunucusuna girdi.")
                
                async with db_pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute("INSERT IGNORE INTO players (username, last_server) VALUES (%s, %s)", (self.username, self.current_label))

                await asyncio.gather(self.pipe_s2c(), self.pipe_c2s())
        except Exception as e: pass
        finally:
            if self in _active_players: _active_players.remove(self)
            for w in (self.client_w, self.server_w):
                if w:
                    try: w.close()
                    except: pass

async def handle_player(cr, cw):
    await PlayerConn(cr, cw).run()

# ══════════════════════════════════════════════════════════
#  HTTP API: SUNUCU KAYDI (AUTO-SCALING) VE DURUM SENKRONU
# ══════════════════════════════════════════════════════════

class HttpHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        # Lua tarafindan yuzuge tiklandiginda cagrilir: "GM1:15;GM2:4" seklinde ozel string doner
        if self.path == "/api/servers":
            try:
                conn = pymysql.connect(host=DB_HOST, user=DB_USER, password=DB_PASS, db=DB_NAME, autocommit=True)
                cur = conn.cursor(pymysql.cursors.DictCursor)
                cur.execute("SELECT label, players FROM servers WHERE (UNIX_TIMESTAMP() - last_seen) < 60")
                rows = cur.fetchall()
                conn.close()
                
                # "GM1:10;GM2:5;" formatına çevirme (Lua parse etsin diye JSON'dan kaçınıldı)
                resp = ";".join([f"{r['label']}:{r['players']}" for r in rows])
                
                self.send_response(200)
                self.end_headers()
                self.wfile.write(resp.encode())
            except Exception as e:
                self.send_response(500)
                self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0: self.send_response(400); self.end_headers(); return
        data = self.rfile.read(length).decode('utf-8')

        # Oyuncu verisini Cuberite'tan kaydet
        if self.path.startswith("/api/player?name="):
            name = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get('name', [''])[0]
            try:
                p_data = json.loads(data)
                conn = pymysql.connect(host=DB_HOST, user=DB_USER, password=DB_PASS, db=DB_NAME, autocommit=True)
                cur = conn.cursor()
                cur.execute("UPDATE players SET pos_x=%s, pos_y=%s, pos_z=%s, health=%s WHERE username=%s",
                            (p_data.get('x',0), p_data.get('y',5), p_data.get('z',0), p_data.get('hp',20), name))
                conn.close()
                self.send_response(200)
                self.end_headers()
            except:
                self.send_response(500)
                self.end_headers()

        # Dinamik Sunucu Kaydi (Auto-Naming: GM1, GM2)
        elif self.path == "/api/register":
            try:
                s_data = json.loads(data)
                host, port = s_data['host'], s_data['port']
                
                conn = pymysql.connect(host=DB_HOST, user=DB_USER, password=DB_PASS, db=DB_NAME, autocommit=True)
                cur = conn.cursor()
                
                # Ayni Host/Port daha once kayitli mi?
                cur.execute("SELECT label FROM servers WHERE host=%s AND port=%s", (host, port))
                row = cur.fetchone()
                
                if row:
                    label = row[0]
                    cur.execute("UPDATE servers SET last_seen=UNIX_TIMESTAMP() WHERE label=%s", (label,))
                else:
                    cur.execute("SELECT COUNT(*) FROM servers")
                    count = cur.fetchone()[0]
                    label = f"GM{count+1}"
                    cur.execute("INSERT INTO servers (label, host, port, last_seen) VALUES (%s, %s, %s, UNIX_TIMESTAMP())", (label, host, port))
                
                conn.close()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({"label": label}).encode())
                print(f"[API] Sunucu Kaydedildi: {label} ({host}:{port})")
            except Exception as e:
                print(f"[API] Kayit Hatasi: {e}")
                self.send_response(500)
                self.end_headers()

    def log_message(self, format, *args): pass

# ══════════════════════════════════════════════════════════
#  BAŞLATICI YÖNTEMLER
# ══════════════════════════════════════════════════════════

def run_http():
    srv = http.server.ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), HttpHandler)
    srv.serve_forever()

def _strip_ansi(text):
    import re
    return re.sub(r'\x1b\[[0-9;]*[mK]|\x1b\[\d*[A-Za-z]|\x1b\(\w', '', text)

def run_bore(port=MC_PORT):
    global _current_bore_addr
    import re
    while True:
        try:
            proc = subprocess.Popen(["bore", "local", str(port), "--to", "bore.pub"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in proc.stdout:
                line = _strip_ansi(line.rstrip())
                if not line: continue
                m = re.search(r"bore\.pub:(\d+)", line)
                if m:
                    _current_bore_addr = f"bore.pub:{m.group(1)}"
                    if MODE == "gameserver" or MODE == "all":
                        _register_with_proxy(_current_bore_addr)
            proc.wait()
        except Exception: pass
        time.sleep(10)

def _register_with_proxy(bore_addr):
    proxy_url = os.environ.get("PROXY_URL", "http://127.0.0.1:8080")
    host, port_str = bore_addr.split(":")
    body = json.dumps({"host": host, "port": int(port_str)}).encode()
    try:
        req = urllib.request.Request(f"{proxy_url}/api/register", data=body, headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=5)
        label = json.loads(resp.read().decode())['label']
        print(f"[REG] Basariyla kayit olundu! Bu sunucunun adi: {label}")
    except:
        print("[REG] HATA: Proxy'e kayit olunamadi.")

def run_cuberite():
    write_configs()
    mc_bin = next(iter(glob.glob("/server/**/Cuberite", recursive=True)), None)
    if not mc_bin: return
    mc_dir = str(pathlib.Path(mc_bin).parent)
    os.chmod(mc_bin, 0o755)
    
    while True:
        subprocess.Popen([mc_bin], cwd=mc_dir).wait()
        time.sleep(5)

async def run_proxy():
    await init_db()
    server = await asyncio.start_server(handle_player, "0.0.0.0", MC_PORT)
    print(f"[PROXY] Hub Mimarisi {MC_PORT} portunda dinliyor...")
    async with server:
        await server.serve_forever()

def main():
    print(f"""
+--------------------------------------------------+
|  Minecraft BungeeCord Hub Engine                 |
|  Mod: {MODE:<43}|
|  DB : {DB_HOST:<43}|
+--------------------------------------------------+""")

    if MODE == "proxy":
        threading.Thread(target=run_http, daemon=True).start()
        asyncio.run(run_proxy())
    elif MODE == "gameserver":
        threading.Thread(target=run_bore, args=(MC_PORT,), daemon=True).start()
        run_cuberite()
    elif MODE == "all":
        threading.Thread(target=run_http, daemon=True).start()
        threading.Thread(target=run_bore, args=(CUBERITE_PORT,), daemon=True).start()
        threading.Thread(target=run_cuberite, daemon=True).start()
        time.sleep(3)
        asyncio.run(run_proxy())

if __name__ == "__main__": main()
