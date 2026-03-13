-- ══════════════════════════════════════════════════════════════════
--  PlayerSave — Cuberite Lua Plugin  v3.0
--  Kaynak: github.com/cuberite/cuberite  (Apache 2.0)
--
--  SORUNUN KÖK NEDENİ (araştırmayla doğrulandı):
--    Cuberite C++ kaynağı (ClientHandle.cpp):
--      cUUID::GenerateVersion3("OfflinePlayer:" + a_Username)
--    → dosya adı: world/data/stats/{uuid-dashed}.json
--                  players/{uuid-dashed}.json
--
--    v1.0 & v1.1 yalnızca "Ray.json" oluşturuyordu.
--    Cuberite hiçbir zaman "Ray.json" okumaz — sadece UUID bazlı okur.
--    Bu yüzden önceki sürümler HİÇBİR ETKİ yapmıyordu.
--
--  v3.0 STRATEJİSİ:
--    1. cClientHandle:GenerateOfflineUUID(username) → 32 char UUID
--    2. cMojangAPI:MakeUUIDDashed(uuid32) → "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
--    3. Bozuk dosya → SİL (Cuberite "not found" → varsayılan ile başlar)
--    4. Başlangıçta tüm mevcut bozuk dosyaları tara ve temizle
--    5. Hata yönetimi: pcall + fallback
--
--  NEDEN SİLİYORUZ, YAZMIYORUZ:
--    stats/{uuid}.json içeriği Cuberite sürümüne göre değişebilir.
--    Boş veya eksik yapı → basic_ios::clear → iostream error → kick.
--    Dosya yoksa → Cuberite gracefully "not found" ile varsayılanları kullanır.
-- ══════════════════════════════════════════════════════════════════

PLUGIN      = nil
local CACHE = {}   -- uuid cache: {username -> uuid_dashed}, bellekte tutulsun

-- ── Yardımcı: Güvenli UUID al ────────────────────────────────────
-- cClientHandle:GenerateOfflineUUID → 32 char (no dashes)
-- cMojangAPI:MakeUUIDDashed         → "xx-xx-xx-xx-xx"
local function GetOfflineUUID(username)
    if CACHE[username] then return CACHE[username] end

    local ok, uuid32 = pcall(function()
        return cClientHandle:GenerateOfflineUUID(username)
    end)

    if not ok or not uuid32 or #uuid32 == 0 then
        LOG("[PlayerSave] UYARI: GenerateOfflineUUID başarısız → " .. tostring(uuid32))
        return nil
    end

    -- Short UUID (32 char) → Long UUID (36 char, with dashes)
    local ok2, uuidDashed = pcall(function()
        return cMojangAPI:MakeUUIDDashed(uuid32)
    end)

    if not ok2 or not uuidDashed or #uuidDashed < 32 then
        -- Manuel fallback: 8-4-4-4-12 formatı
        if #uuid32 == 32 then
            uuidDashed = string.format("%s-%s-%s-%s-%s",
                uuid32:sub(1,8), uuid32:sub(9,12),
                uuid32:sub(13,16), uuid32:sub(17,20),
                uuid32:sub(21,32))
        else
            LOG("[PlayerSave] UYARI: UUID dönüştürme başarısız: " .. username)
            return nil
        end
    end

    CACHE[username] = uuidDashed
    return uuidDashed
end

-- ── Yardımcı: Dizin garantile ────────────────────────────────────
local function EnsureDir(path)
    os.execute('mkdir -p "' .. path .. '" 2>/dev/null')
    os.execute('chmod 777 "' .. path .. '" 2>/dev/null')
end

-- ── Yardımcı: Dosya geçerli JSON mu? ────────────────────────────
-- Cuberite basic_ios::clear fırlatır eğer:
--   • Dosya boşsa (0 byte)
--   • İçerik { ile başlamıyorsa
--   • stats dosyasında "stats" key'i yoksa
local function IsValidJSON(path)
    local f = io.open(path, "r")
    if not f then return nil end   -- dosya yok
    local content = f:read("*all")
    f:close()
    if not content or #content < 2 then return false end
    return content:find("^%s*{") ~= nil   -- { ile başlıyor mu?
end

-- ── Yardımcı: Bozuk dosyayı güvenle kaldır ─────────────────────
local function RemoveCorrupt(path, label)
    -- Önce yedekle
    local bak = path .. ".corrupt_" .. os.time() .. ".bak"
    if not os.rename(path, bak) then
        os.remove(path)
        LOG("[PlayerSave] 🗑 Silindi: " .. path .. " (" .. label .. ")")
    else
        LOG("[PlayerSave] 📦 Yedeklendi: " .. bak .. " (" .. label .. ")")
    end
end

-- ── Ana düzeltme fonksiyonu ──────────────────────────────────────
-- Hem UUID hem de isim tabanlı dosyaları kontrol eder.
-- Bozuk dosyaları siler → Cuberite varsayılanla devam eder.
local function FixPlayerFiles(username, uuidDashed)
    local statsDir   = "world/data/stats"
    local playersDir = "players"

    EnsureDir(statsDir)
    EnsureDir(playersDir)

    -- Kontrol edilecek tüm yollar
    local candidates = {
        -- Stats dosyaları (Cuberite bu dosyaları okurken hata fırlatır)
        { path = statsDir .. "/" .. uuidDashed .. ".json", label = "stats/uuid",    critical = true  },
        { path = statsDir .. "/" .. username   .. ".json", label = "stats/name",    critical = true  },
        -- Player save dosyaları
        { path = playersDir .. "/" .. uuidDashed .. ".json", label = "player/uuid", critical = false },
        { path = playersDir .. "/" .. username   .. ".json", label = "player/name", critical = false },
    }

    local fixed = 0
    for _, c in ipairs(candidates) do
        local valid = IsValidJSON(c.path)
        if valid == false then
            -- Dosya VAR ama bozuk → sil
            RemoveCorrupt(c.path, username .. "/" .. c.label)
            fixed = fixed + 1
        end
        -- valid == nil → dosya yok → sorun yok, Cuberite oluşturur
        -- valid == true → geçerli → sorun yok
    end

    return fixed
end

-- ── HOOK_LOGIN ──────────────────────────────────────────────────
-- Authentication ÖNCE çalışır → Cuberite dosyaları okumadan ÖNCE
function OnLogin(Client, ProtocolVersion, Username)
    if not Username or Username == "" then return false end

    local uuidDashed = GetOfflineUUID(Username)
    if not uuidDashed then
        -- UUID alınamadı ama girişi engelleme — dizinleri garantile
        EnsureDir("world/data/stats")
        EnsureDir("players")
        LOG("[PlayerSave] ⚠️  UUID alınamadı: " .. Username .. " — dizinler hazırlandı")
        return false
    end

    local fixed = FixPlayerFiles(Username, uuidDashed)

    if fixed > 0 then
        LOG("[PlayerSave] ✅ " .. Username .. " (" .. uuidDashed:sub(1,8) .. "…) → " .. fixed .. " bozuk dosya temizlendi")
    else
        LOG("[PlayerSave] ✅ " .. Username .. " (" .. uuidDashed:sub(1,8) .. "…) → dosyalar geçerli")
    end

    return false  -- girişi ENGELLEME
end

-- ── HOOK_PLAYER_DESTROYED ────────────────────────────────────────
-- Oyuncu çıktıktan sonra bıraktığı bozuk dosyaları temizle.
-- Cuberite bazen çıkışta sıfır byte'lık dosya bırakır.
function OnPlayerDestroyed(Player)
    local username = Player:GetName()
    if not username or username == "" then return false end

    -- Player objesinden UUID almayı dene
    local uuidDashed = nil
    local ok, rawUUID = pcall(function() return Player:GetUUID() end)
    if ok and rawUUID then
        -- GetUUID() → cUUID objesi veya string döner
        local uok, ustr = pcall(function()
            if type(rawUUID) == "string" then
                return rawUUID
            else
                return rawUUID:ToLongString()
            end
        end)
        if uok and ustr and #ustr >= 32 then
            uuidDashed = ustr:find("-") and ustr or nil
            if not uuidDashed and #ustr == 32 then
                -- Short UUID → dashed
                local dok, dstr = pcall(function()
                    return cMojangAPI:MakeUUIDDashed(ustr)
                end)
                if dok then uuidDashed = dstr end
            end
        end
    end

    -- UUID alınamadıysa cache'den veya yeniden hesapla
    if not uuidDashed then
        uuidDashed = GetOfflineUUID(username)
    end

    if not uuidDashed then return false end

    local fixed = FixPlayerFiles(username, uuidDashed)
    if fixed > 0 then
        LOG("[PlayerSave] 🔧 Çıkış sonrası " .. username .. " → " .. fixed .. " dosya onarıldı")
    end

    return false
end

-- ── Başlangıç Taraması ───────────────────────────────────────────
-- Sunucu başlarken mevcut tüm bozuk stats dosyalarını temizle.
-- Birikmiş 0-byte dosyalar varsa bu temizler.
local function StartupScan()
    local statsDir = "world/data/stats"
    EnsureDir(statsDir)
    EnsureDir("players")

    local count = 0
    -- Lua'da glob yok, cFile varsa kullan
    local ok, result = pcall(function()
        return cFile:GetFolderContents(statsDir)
    end)

    if ok and result then
        for _, fname in ipairs(result) do
            if fname:match("%.json$") then
                local fpath = statsDir .. "/" .. fname
                local valid = IsValidJSON(fpath)
                if valid == false then
                    RemoveCorrupt(fpath, "startup-scan")
                    count = count + 1
                end
            end
        end
    else
        -- cFile yoksa shell ile tarama yap
        local scanFile = "/tmp/ps_scan_result.txt"
        os.execute('find "' .. statsDir .. '" -name "*.json" -empty > "' .. scanFile .. '" 2>/dev/null')
        local f = io.open(scanFile, "r")
        if f then
            for line in f:lines() do
                line = line:match("^%s*(.-)%s*$")
                if line ~= "" then
                    RemoveCorrupt(line, "startup-empty")
                    count = count + 1
                end
            end
            f:close()
            os.remove(scanFile)
        end
    end

    if count > 0 then
        LOG("[PlayerSave] 🧹 Başlangıç taraması: " .. count .. " bozuk dosya temizlendi")
    else
        LOG("[PlayerSave] ✅ Başlangıç taraması: Bozuk dosya bulunamadı")
    end
end

-- ── Konsoldan UUID sorgulama komutu ─────────────────────────────
local function HandleUUIDCommand(Split, Player)
    if not Split[2] then
        Player:SendMessage("Kullanım: /uuid <oyuncu_adı>")
        return true
    end
    local name = Split[2]
    local uuid = GetOfflineUUID(name)
    if uuid then
        Player:SendMessage("[PlayerSave] " .. name .. " UUID: " .. uuid)
    else
        Player:SendMessage("[PlayerSave] UUID alınamadı: " .. name)
    end
    return true
end

-- ── Başlatma ─────────────────────────────────────────────────────
function Initialize(Plugin)
    Plugin:SetName("PlayerSave")
    Plugin:SetVersion(3)
    PLUGIN = Plugin

    cPluginManager.AddHook(cPluginManager.HOOK_LOGIN,            OnLogin)
    cPluginManager.AddHook(cPluginManager.HOOK_PLAYER_DESTROYED, OnPlayerDestroyed)

    -- Debug komutu (opsiyonel — admin'ler için)
    cPluginManager:BindCommand("/uuid", "playersave.admin", HandleUUIDCommand,
        " ~ Oyuncu offline UUID'sini göster")

    -- Başlangıç taraması
    StartupScan()

    LOG("╔══════════════════════════════════════╗")
    LOG("║  PlayerSave v3.0 yüklendi             ║")
    LOG("║  Algoritma: OfflinePlayer:+MD5 (v3)   ║")
    LOG("║  Dosyalar: {uuid-dashed}.json          ║")
    LOG("║  HOOK_LOGIN + HOOK_PLAYER_DESTROYED    ║")
    LOG("╚══════════════════════════════════════╝")

    return true
end

function OnDisable()
    CACHE = {}
    LOG("[PlayerSave] v3.0 devre dışı — cache temizlendi")
end
