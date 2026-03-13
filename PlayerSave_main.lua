-- ══════════════════════════════════════════════════════════════════
--  PlayerSave — Cuberite Lua Plugin  v2.0  (UUID-TABANLI DÜZELTME)
--  Cuberite'in player/stats dosyası yönetimini stabilize eder.
--
--  v1.0 HATASI (eski sürüm):
--    Dosyalar OYUNCU ADI ile oluşturuluyordu: stats/Ray.json
--    Ama Cuberite GERÇEKTE UUID ile okur:     stats/{uuid}.json
--    Bu yüzden v1.0 HİÇBİR ETKİ yapmıyordu!
--
--  v2.0 DÜZELTME:
--    cClientHandle:GenerateOfflineUUID(username) ile UUID alınır
--    UUID long format'a çevrilir: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
--    Hem stats hem de player save dosyaları UUID adıyla düzeltilir
--    Bozuk dosyalar SİLİNİR → Cuberite yeni oyuncu olarak kabul eder
--
--  HOOKS:
--    HOOK_LOGIN → Authentication ÖNCE çalışır → dosyaları hazırlar
-- ══════════════════════════════════════════════════════════════════

PLUGIN = nil

local EMPTY_STATS = '{"stats":{}}'

-- ── Yardımcı: Dizin garantile ────────────────────────────────────
local function EnsureDir(path)
    os.execute('mkdir -p "' .. path .. '" 2>/dev/null')
    os.execute('chmod 777 "' .. path .. '" 2>/dev/null')
end

-- ── UUID'yi long format'a çevir (32 char → xx-xx-xx-xx-xx) ───────
-- cClientHandle:GenerateOfflineUUID → "550e8400e29b41d4a716446655440000" (no dashes)
-- Cuberite dosya adı formatı       → "550e8400-e29b-41d4-a716-446655440000"
local function FormatLongUUID(uuid32)
    if not uuid32 or #uuid32 ~= 32 then return nil end
    return string.format("%s-%s-%s-%s-%s",
        uuid32:sub(1, 8),
        uuid32:sub(9, 12),
        uuid32:sub(13, 16),
        uuid32:sub(17, 20),
        uuid32:sub(21, 32)
    )
end

-- ── Dosya geçerliliği kontrolü ───────────────────────────────────
-- Boş (0 byte) veya JSON başlamıyorsa BOZUK kabul et
local function IsFileValid(path)
    local f = io.open(path, "r")
    if not f then return false end  -- dosya yok → geçersiz
    local content = f:read("*all")
    f:close()
    if not content or content == "" then return false end  -- boş dosya
    local trimmed = content:match("^%s*(.-)%s*$")
    return trimmed:sub(1, 1) == "{"  -- JSON başlıyor mu?
end

-- ── Stats dosyası geçerlilik kontrolü ────────────────────────────
-- Cuberite "stats" key'ini bekliyor
local function IsValidStatsFile(path)
    if not IsFileValid(path) then return false end
    local f = io.open(path, "r")
    if not f then return false end
    local content = f:read("*all")
    f:close()
    return content:find('"stats"') ~= nil
end

-- ── Stats dosyası yaz ────────────────────────────────────────────
local function WriteStatsFile(path, label)
    local f = io.open(path, "w")
    if f then
        f:write(EMPTY_STATS)
        f:close()
        os.execute('chmod 666 "' .. path .. '" 2>/dev/null')
        LOG("[PlayerSave] Stats dosyası yazıldı: " .. path .. " (" .. label .. ")")
        return true
    end
    LOG("[PlayerSave] UYARI: Yazılamadı: " .. path)
    return false
end

-- ── Bozuk dosyayı yedekle ve kaldır ─────────────────────────────
local function BackupAndRemove(path, label)
    local backup = path .. ".corrupt_bak"
    if os.rename(path, backup) then
        LOG("[PlayerSave] Bozuk dosya yedeklendi: " .. backup .. " (" .. label .. ")")
    else
        os.remove(path)
        LOG("[PlayerSave] Bozuk dosya silindi: " .. path .. " (" .. label .. ")")
    end
end

-- ── Ana Giriş Hook'u ─────────────────────────────────────────────
-- HOOK_LOGIN: Authentication ÖNCESI çalışır
-- Bu noktada UUID hesaplanır ve bozuk dosyalar temizlenir
-- Cuberite'in dosyaları okuma girişiminden ÖNCE düzeltme yapılır
function OnLogin(Client, ProtocolVersion, Username)
    if not Username or Username == "" then return false end

    -- ─ 1. Offline UUID hesapla ─────────────────────────────────
    -- Sunucu offline moddaysa UUID deterministik olarak username'den türetilir
    local uuid32 = cClientHandle:GenerateOfflineUUID(Username)
    local uuidLong = FormatLongUUID(uuid32)

    if not uuidLong then
        LOG("[PlayerSave] UYARI: UUID alınamadı, " .. Username .. " için isim tabanlı fallback")
        uuidLong = nil
    else
        LOG("[PlayerSave] " .. Username .. " → UUID: " .. uuidLong)
    end

    -- ─ 2. Stats dosyasını düzelt ───────────────────────────────
    local statsDir = "world/data/stats"
    EnsureDir(statsDir)

    -- UUID tabanlı (yeni Cuberite) — ASIL SORUNUN ÇÖZÜMÜ
    if uuidLong then
        local statsUUID = statsDir .. "/" .. uuidLong .. ".json"
        if not IsValidStatsFile(statsUUID) then
            -- Dosya var ama bozuksa → yedekle ve temizle
            local f = io.open(statsUUID, "r")
            if f then
                f:close()
                BackupAndRemove(statsUUID, Username)
            end
            WriteStatsFile(statsUUID, Username)
        end
    end

    -- İsim tabanlı (eski Cuberite fallback)
    local statsName = statsDir .. "/" .. Username .. ".json"
    if not IsValidStatsFile(statsName) then
        local f = io.open(statsName, "r")
        if f then f:close(); BackupAndRemove(statsName, Username) end
        WriteStatsFile(statsName, Username)
    end

    -- ─ 3. Player save dosyasını düzelt ────────────────────────
    -- Bozuksa SİL → Cuberite yeni oyuncu varsayılanlarını kullanır
    -- (YENİDEN YAZMIYORUZ: player save formatı karmaşık)
    local playersDir = "players"
    EnsureDir(playersDir)

    if uuidLong then
        local playerUUID = playersDir .. "/" .. uuidLong .. ".json"
        if not IsFileValid(playerUUID) then
            local f = io.open(playerUUID, "r")
            if f then
                -- Dosya VAR ama BOZUK → sil
                f:close()
                BackupAndRemove(playerUUID, Username)
                LOG("[PlayerSave] " .. Username .. " player save sıfırlandı (varsayılanlar kullanılacak)")
            end
            -- Yoksa: Cuberite kendisi oluşturur, sorun yok
        end
    end

    -- İsim tabanlı player save (eski sürümler)
    local playerName = playersDir .. "/" .. Username .. ".json"
    if not IsFileValid(playerName) then
        local f = io.open(playerName, "r")
        if f then f:close(); BackupAndRemove(playerName, Username) end
    end

    LOG("[PlayerSave] " .. Username .. " için dosyalar hazır — bağlantı devam edebilir")
    return false  -- girişi ENGELLEME
end

-- ── Çıkış Hook'u ─────────────────────────────────────────────────
function OnPlayerDestroyed(Player)
    local username = Player:GetName()

    -- UUID al
    local uuid32 = ""
    local ok, result = pcall(function() return Player:GetUUID() end)
    if ok and result then
        uuid32 = result
    end
    local uuidLong = FormatLongUUID(uuid32)

    -- Çıkışta stats bozulduysa onar
    local statsDir = "world/data/stats"

    if uuidLong then
        local statsUUID = statsDir .. "/" .. uuidLong .. ".json"
        if not IsValidStatsFile(statsUUID) then
            WriteStatsFile(statsUUID, username .. "/çıkış")
        end
    end

    local statsName = statsDir .. "/" .. username .. ".json"
    if not IsValidStatsFile(statsName) then
        WriteStatsFile(statsName, username .. "/çıkış-isim")
    end

    return false
end

-- ── Başlatma ─────────────────────────────────────────────────────
function Initialize(Plugin)
    Plugin:SetName("PlayerSave")
    Plugin:SetVersion(2)
    PLUGIN = Plugin

    cPluginManager.AddHook(cPluginManager.HOOK_LOGIN,            OnLogin)
    cPluginManager.AddHook(cPluginManager.HOOK_PLAYER_DESTROYED, OnPlayerDestroyed)

    EnsureDir("world/data/stats")
    EnsureDir("players")

    LOG("====================================")
    LOG("[PlayerSave] v2.0 yüklendi")
    LOG("[PlayerSave] DÜZELTME: Artık UUID tabanlı dosyalar onarılıyor")
    LOG("[PlayerSave]   world/data/stats/{uuid}.json")
    LOG("[PlayerSave]   players/{uuid}.json")
    LOG("[PlayerSave] Eski sürüm yalnızca Ray.json yazıyordu (EFEKSİZ)")
    LOG("====================================")

    return true
end

function OnDisable()
    LOG("[PlayerSave] v2.0 devre dışı")
end
