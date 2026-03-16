local ProxyURL = "http://127.0.0.1:{PORT}"

local function Split(str, sep)
    local res = {}
    for w in string.gmatch(str, "([^"..sep.."]+)") do table.insert(res, w) end
    return res
end

function Initialize(Plugin)
    Plugin:SetName("WCHub")
    Plugin:SetVersion(12)
    cPluginManager:AddHook(cPluginManager.HOOK_PLAYER_SPAWNED, OnPlayerSpawned)
    cPluginManager:AddHook(cPluginManager.HOOK_EXECUTE_COMMAND, OnCommand)
    LOG("[HUB] WCHub Saf Sohbet Sistemi Aktif!")
    return true
end

function OnPlayerSpawned(Player)
    Player:GetWorld():ScheduleTask(20, function() SendServerList(Player) end)
end

function OnCommand(Player, CommandSplit, EntireCommand)
    local cmd = string.lower(CommandSplit[1] or "")
    if cmd == "/hub" or cmd == "/sunucu" then
        SendServerList(Player)
        return true
    end
    return false
end

function SendServerList(Player)
    local PlayerName = Player:GetName()
    local World = Player:GetWorld()
    if type(cUrlClient) == "nil" then return end
    cUrlClient:Get(ProxyURL .. "/api/servers", {
        OnSuccess = function(Body)
            World:ScheduleTask(0, function()
                local TargetPlayer = nil
                cRoot:Get():FindAndDoWithPlayer(PlayerName, function(P) TargetPlayer = P end)
                if not TargetPlayer or not Body or Body == "" then return end

                TargetPlayer:SendMessageInfo(" ")
                TargetPlayer:SendMessageInfo("§8§m                                     ")
                TargetPlayer:SendMessageInfo("§3§l      ♦ WC NETWORK AĞI ♦      ")
                TargetPlayer:SendMessageInfo("§7  Hızlı geçiş için hedefe tıklayın:")
                TargetPlayer:SendMessageInfo(" ")

                local servers = Split(Body, ";")
                for i, srv in ipairs(servers) do
                    local parts = Split(srv, ":")
                    if #parts == 2 then
                        local msg = cCompositeChat()
                        msg:ParseText("  §8▪ §b" .. parts[1] .. " §7(Aktif: §e" .. parts[2] .. "§7)   ")
                        msg:AddRunCommandPart("§a§n[BAĞLAN]", "/wc_transfer " .. parts[1])
                        TargetPlayer:SendMessage(msg)
                    end
                end
                TargetPlayer:SendMessageInfo("§8§m                                     ")
                TargetPlayer:SendMessageInfo(" ")
            end)
        end
    })
end
