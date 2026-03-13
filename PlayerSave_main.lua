-- ══════════════════════════════════════════════════════════════════
--  PlayerSave — Cuberite Lua Plugin  v4.0 (Render.com Fix)
-- ══════════════════════════════════════════════════════════════════

PLUGIN = nil
local CACHE = {}

-- ── Dizin Garantileme (Kritik Render.com Çözümü) ──────────────────
-- İlk girişte fırlatılan iostream hatasının sebebi C++'ın olmayan 
-- klasöre dosya yazamamasıdır. Bu fonksiyon Linux komutlarıyla klasörleri zorla açar.
local function EnsureDirs()
    local dirs = {
        "world/stats", 
        "world/players", 
        "world/playerdata",
        "players",
        "stats"
    }
    for _, dir in ipairs(dirs) do
        -- Klasörleri oluştur ve yazma yetkisini tam (777) ver
        os.execute('mkdir -p "' .. dir .. '" 2>/dev/null')
        os.execute('chmod -R 777 "' .. dir .. '" 2>/dev/null')
    end
end

-- ── Güvenli UUID Alma ─────────────────────────────────────────────
local function GetOfflineUUID(username)
    if CACHE[username] then return CACHE[username] end
    local uuidDashed = nil

    -- Yöntem 1: Yeni Nesil Cuberite Sürümleri (cUUID sınıfı)
    if cUUID then
        pcall(function()
            local cuuid = cUUID()
            cuuid:GenerateVersion3("OfflinePlayer:" .. username)
            uuidDashed = cuuid:ToLongString()
        end)
    end

    -- Yöntem 2: Eski Nesil Cuberite Sürümleri (cClientHandle)
    if not uuidDashed and cClientHandle and cClientHandle.GenerateOfflineUUID then
        pcall(function()
            local uuid32 = cClientHandle:GenerateOfflineUUID(username)
            if uuid32 and cMojangAPI then
                uuidDashed = cMojangAPI:MakeUUIDDashed(uuid32)
            end
        end)
    end

    if uuidDashed then
        CACHE[username] = uuidDashed
    else
        LOG("[PlayerSave] ⚠️ UUID uretilemedi, Cuberite surumu eski olabilir: " .. username)
    end
    return uuidDashed
end

-- ── Dosya Geçerlilik Kontrolü ─────────────────────────────────────
local function IsValidJSON(path)
    local f = io.open(path, "r")
    if not f then return nil end -- Dosya yoksa sorun değil, Cuberite oluşturur.
    local content = f:read("*all")
    f:close()
    
    if not content or #content < 2 then return false end -- Dosya 0 byte ise bozuktur.
    if not content:find("^%s*{") then return false end   -- JSON başlangıcı yoksa bozuktur.
    return true
end

-- ── Bozuk Dosya Temizleyici ───────────────────────────────────────
local function FixPlayerFiles(username, uuidDashed)
    local fixed = 0
    local pathsToCheck = {}

    -- Olası tüm dosya yollarını hedefe ekle
    if uuidDashed then
        table.insert(pathsToCheck, "world/stats/" .. uuidDashed .. ".json")
        table.insert(pathsToCheck, "world/players/" .. uuidDashed .. ".json")
        table.insert(pathsToCheck, "players/" .. uuidDashed .. ".json")
    end

    table.insert(pathsToCheck, "world/stats/" .. username .. ".json")
    table.insert(pathsToCheck, "world/players/" .. username .. ".json")
    table.insert(pathsToCheck, "players/" .. username .. ".json")

    for _, path in ipairs(pathsToCheck) do
        local valid = IsValidJSON(path)
        if valid == false then
            os.remove(path)
            LOG("[PlayerSave] 🗑️ Bozuk dosya silindi: " .. path)
            fixed = fixed + 1
        end
    end
    return fixed
end

-- ── Kancalar (Hooks) ──────────────────────────────────────────────
function OnLogin(Client, ProtocolVersion, Username)
    if not Username or Username == "" then return false end
    
    -- Oyuncu girerken her ihtimale karşı klasörleri ve yetkileri kontrol et
    EnsureDirs() 
    
    local uuidDashed = GetOfflineUUID(Username)
    local fixed = FixPlayerFiles(Username, uuidDashed)
    
    if fixed > 0 then
        LOG("[PlayerSave] ✅ " .. Username .. " icin " .. fixed .. " bozuk dosya onarildi.")
    end
    return false -- Girişe izin ver
end

function OnPlayerDestroyed(Player)
    local username = Player:GetName()
    if not username or username == "" then return false end
    
    -- Oyuncu çıkış yaparken Cuberite 0 byte dosya bırakırsa hemen sil
    local uuidDashed = GetOfflineUUID(username)
    FixPlayerFiles(username, uuidDashed)
    return false
end

-- ── Eklenti Başlatma ──────────────────────────────────────────────
function Initialize(Plugin)
    Plugin:SetName("PlayerSave")
    Plugin:SetVersion(4)
    PLUGIN = Plugin

    -- Sunucu açıldığında ilk iş klasörleri oluştur ve 777 yetkisi ver
    EnsureDirs()
    LOG("[PlayerSave] 📁 Render.com dizinleri ve yetkileri kontrol edildi.")

    cPluginManager.AddHook(cPluginManager.HOOK_LOGIN, OnLogin)
    cPluginManager.AddHook(cPluginManager.HOOK_PLAYER_DESTROYED, OnPlayerDestroyed)

    LOG("╔══════════════════════════════════════╗")
    LOG("║  PlayerSave v4.0 (Render.com Fix)    ║")
    LOG("║  Aktif: Klasor zorlama & UUID Onarim ║")
    LOG("╚══════════════════════════════════════╝")
    return true
end

function OnDisable()
    CACHE = {}
    LOG("[PlayerSave] Devre disi birakildi.")
end
