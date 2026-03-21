import utime


def safe_import(name):
    try:
        return __import__(name)
    except Exception:
        return None


def safe_call(func, *args):
    if not func:
        return None
    try:
        return func(*args)
    except Exception:
        return None


def ok_value(value):
    return value not in (None, -1, "")


def mask_value(value, enabled):
    if (not enabled) or (not ok_value(value)):
        return value
    text = str(value)
    if len(text) <= 8:
        return text
    return text[:4] + ("*" * (len(text) - 8)) + text[-4:]


def wall_time_ms():
    try:
        return int(utime.time() * 1000)
    except Exception:
        return 0


def measure_step(step_name, timings, func, *args):
    started = utime.ticks_ms()
    result = func(*args)
    if isinstance(timings, dict):
        timings[step_name] = utime.ticks_diff(utime.ticks_ms(), started)
    return result


def safe_attr_call(module, names, *args):
    if not module:
        return None, ""
    for name in names:
        if hasattr(module, name):
            return safe_call(getattr(module, name), *args), name
    return None, ""


def parse_reg_entry(entry):
    if (not isinstance(entry, (list, tuple))) or len(entry) < 6:
        return None
    return {
        "state": entry[0],
        "lac": entry[1],
        "cid": entry[2],
        "rat": entry[3],
        "reject_cause": entry[4],
        "psc": entry[5],
    }


def parse_operator_info(raw):
    if (not isinstance(raw, (list, tuple))) or len(raw) < 4:
        return None
    return {
        "long_name": raw[0],
        "short_name": raw[1],
        "mcc": raw[2],
        "mnc": raw[3],
    }


def parse_pdp_context(raw, ip_type):
    if (not isinstance(raw, (list, tuple))) or len(raw) < 5:
        return None
    return {
        "ip_type": ip_type,
        "state": raw[0],
        "reconnect": raw[1],
        "ip_address": raw[2],
        "dns_primary": raw[3],
        "dns_secondary": raw[4],
    }


def parse_data_context(raw):
    if (not isinstance(raw, (list, tuple))) or len(raw) < 3:
        return None
    ctx = {
        "profile_id": raw[0],
        "ip_type_code": raw[1],
        "contexts": [],
    }
    if raw[1] == 2 and len(raw) >= 4:
        ipv4 = parse_pdp_context(raw[2], "IP")
        ipv6 = parse_pdp_context(raw[3], "IPV6")
        if ipv4:
            ctx["contexts"].append(ipv4)
        if ipv6:
            ctx["contexts"].append(ipv6)
    else:
        ip_type = "IPV6" if raw[1] == 1 else "IP"
        parsed = parse_pdp_context(raw[2], ip_type)
        if parsed:
            ctx["contexts"].append(parsed)

    preferred = None
    for item in ctx["contexts"]:
        if item.get("state") == 1:
            preferred = item
            break
    if preferred is None and ctx["contexts"]:
        preferred = ctx["contexts"][0]

    if preferred:
        ctx["cid_preferred"] = ctx["profile_id"]
        ctx["ip_type"] = preferred.get("ip_type")
        ctx["ip_address"] = preferred.get("ip_address")
        ctx["cid"] = ctx["profile_id"]
        ctx["state"] = preferred.get("state")
        ctx["source"] = "dataCall.getInfo"
    return ctx


def _signal_quality(csq):
    if not isinstance(csq, int) or csq < 0:
        return "unknown"
    if csq >= 20:
        return "good"
    if csq >= 10:
        return "fair"
    return "weak"


def gather_modem_info(cfg, mask_sensitive):
    modem = safe_import("modem")
    info = {
        "device_id": cfg.DEVICE_ID,
        "device_name": getattr(cfg, "DEVICE_NAME", ""),
        "tenant_id": cfg.TENANT_ID,
        "access_mode": cfg.ACCESS_MODE,
        "fw_version_config": cfg.FW_VERSION,
        "ts": wall_time_ms(),
    }
    if modem:
        model = safe_call(getattr(modem, "getDevModel", None))
        imei = safe_call(getattr(modem, "getDevImei", None))
        fw_version = safe_call(getattr(modem, "getDevFwVersion", None))
        sn = safe_call(getattr(modem, "getDevSN", None))
        product_id = safe_call(getattr(modem, "getDevProductId", None))
        mac = safe_call(getattr(modem, "getDevMAC", None))
        if ok_value(model):
            info["module_model"] = model
        if ok_value(imei):
            info["imei"] = mask_value(imei, mask_sensitive)
        if ok_value(fw_version):
            info["firmware_version"] = fw_version
        if ok_value(sn):
            info["serial_number"] = mask_value(sn, mask_sensitive)
        if ok_value(product_id):
            info["product_id"] = product_id
        if ok_value(mac):
            info["mac_address"] = mask_value(mac, mask_sensitive)
    return info


def gather_sim_info(mask_sensitive):
    sim = safe_import("sim")
    data = {
        "available": bool(sim),
        "ready": False,
    }
    if not sim:
        return data

    status = safe_call(getattr(sim, "getStatus", None))
    data["status"] = status
    data["ready"] = status == 1
    data["inserted"] = status not in (None, 0, -1)

    iccid = safe_call(getattr(sim, "getIccid", None))
    imsi = safe_call(getattr(sim, "getImsi", None))
    phone_number = safe_call(getattr(sim, "getPhoneNumber", None))
    cur_simid = safe_call(getattr(sim, "getCurSimid", None)) if hasattr(sim, "getCurSimid") else None

    if ok_value(iccid):
        data["iccid"] = mask_value(iccid, mask_sensitive)
    if ok_value(imsi):
        data["imsi"] = mask_value(imsi, mask_sensitive)
    if ok_value(phone_number):
        data["phone_number"] = mask_value(phone_number, mask_sensitive)
    if ok_value(cur_simid) or cur_simid == 0:
        data["current_sim_id"] = cur_simid
    return data


def gather_network_info():
    net = safe_import("net")
    check_net = safe_import("checkNet")
    data = {
        "available": bool(net),
    }
    if not net:
        return data

    reg_raw, reg_source = safe_attr_call(net, ["getState"])
    voice = None
    data_reg = None
    if isinstance(reg_raw, (list, tuple)) and len(reg_raw) >= 2:
        voice = parse_reg_entry(reg_raw[0])
        data_reg = parse_reg_entry(reg_raw[1])
        data["registration_raw"] = reg_raw
        data["registration_source"] = reg_source

    operator_raw, operator_source = safe_attr_call(net, ["getOperatorName", "operatorName"])
    operator_info = parse_operator_info(operator_raw)
    serving_ci, _ = safe_attr_call(net, ["getServingCi"])
    serving_lac, _ = safe_attr_call(net, ["getServingLac"])
    serving_mcc, _ = safe_attr_call(net, ["getServingMcc"])
    serving_mnc, _ = safe_attr_call(net, ["getServingMnc"])
    csq, _ = safe_attr_call(net, ["csqQueryPoll"])
    signal_detail, signal_source = safe_attr_call(net, ["getSignal"], 1)
    nitz, nitz_source = safe_attr_call(net, ["nitzTime"])
    cells, cells_source = safe_attr_call(net, ["getCellInfo", "currentCellInfo"])

    if voice:
        data["voice_registration"] = voice
    if data_reg:
        data["data_registration"] = data_reg
        state = data_reg.get("state")
        data["registered"] = state in (1, 5, 8)
        data["registration"] = {
            "registered": data["registered"],
            "source": "net.getState",
            "stat": state,
            "cereg": {"n": 3, "stat": state},
            "cgreg": {"n": 0, "stat": state},
            "creg": {"n": 0, "stat": voice.get("state") if voice else state},
        }
    if operator_info:
        operator_info["source"] = operator_source
        data["operator"] = operator_info

    signal = {}
    if ok_value(serving_ci):
        signal["serving_ci"] = serving_ci
    if ok_value(serving_lac):
        signal["serving_lac"] = serving_lac
    if ok_value(serving_mcc):
        signal["serving_mcc"] = serving_mcc
    if ok_value(serving_mnc):
        signal["serving_mnc"] = serving_mnc
    if ok_value(csq):
        signal["csq"] = csq
        signal["quality"] = _signal_quality(csq)
    if ok_value(signal_detail):
        signal["detail"] = signal_detail
        signal["detail_source"] = signal_source
    if signal:
        data["signal"] = signal

    if ok_value(nitz):
        data["nitz_time"] = {
            "raw": nitz,
            "source": nitz_source,
        }
    if ok_value(cells):
        data["cell_scan"] = {
            "raw": cells,
            "source": cells_source,
        }

    if check_net and hasattr(check_net, "waitNetworkReady"):
        ready = safe_call(check_net.waitNetworkReady, 1)
        if isinstance(ready, (list, tuple)) and len(ready) >= 2:
            data["network_ready"] = {
                "stage": ready[0],
                "state": ready[1],
            }
    return data


def gather_data_context():
    data_call = safe_import("dataCall")
    data = {
        "available": bool(data_call),
    }
    if not data_call:
        return data

    raw = safe_call(getattr(data_call, "getInfo", None), 1, 2)
    if raw in (None, -1):
        raw = safe_call(getattr(data_call, "getInfo", None), 1, 0)
    parsed = parse_data_context(raw)
    if parsed:
        data.update(parsed)
        data["raw"] = raw
    return data


def _fill_cell_serving_from_signal(data, signal):
    if not isinstance(signal, dict):
        return
    for source_key, target_key in (
        ("serving_ci", "ci"),
        ("serving_lac", "lac"),
        ("serving_mcc", "mcc"),
        ("serving_mnc", "mnc"),
    ):
        value = signal.get(source_key)
        if ok_value(value):
            data["serving"][target_key] = value


def _fill_cell_serving_from_raw(data):
    raw = data.get("raw")
    if not (isinstance(raw, (list, tuple)) and len(raw) >= 3):
        return
    rows = raw[2]
    if not (isinstance(rows, (list, tuple)) and rows):
        return
    row = rows[0]
    if not isinstance(row, (list, tuple)):
        return
    mapping = (
        (1, "ci"),
        (2, "mcc"),
        (3, "mnc"),
        (5, "lac"),
    )
    for index, key in mapping:
        if len(row) > index and ok_value(row[index]):
            data["serving"][key] = row[index]


def _fill_cell_neighbors_from_raw(data):
    raw = data.get("raw")
    if not (isinstance(raw, (list, tuple)) and len(raw) >= 3):
        return
    rows = raw[2]
    if not isinstance(rows, (list, tuple)):
        return
    collected = {
        "ci": [],
        "mcc": [],
        "mnc": [],
        "lac": [],
    }
    mapping = (
        (1, "ci"),
        (2, "mcc"),
        (3, "mnc"),
        (5, "lac"),
    )
    for row in rows:
        if not isinstance(row, (list, tuple)):
            continue
        for index, key in mapping:
            if len(row) > index and ok_value(row[index]):
                collected[key].append(row[index])
    for key in ("ci", "mcc", "mnc", "lac"):
        if collected[key] and key not in data["neighbors"]:
            data["neighbors"][key] = collected[key]


def gather_cell_info(network_info=None):
    net = safe_import("net")
    if not net and not isinstance(network_info, dict):
        return {"available": False}

    data = {
        "available": True,
        "serving": {},
        "neighbors": {},
    }

    if isinstance(network_info, dict):
        _fill_cell_serving_from_signal(data, network_info.get("signal"))
        cell_scan = network_info.get("cell_scan")
        if isinstance(cell_scan, dict):
            raw = cell_scan.get("raw")
            if ok_value(raw):
                data["raw"] = raw
                data["raw_source"] = cell_scan.get("source") or "reused.cell_scan"
                _fill_cell_serving_from_raw(data)
                _fill_cell_neighbors_from_raw(data)

    if net:
        if not data["serving"]:
            for method_name, key in (
                ("getServingCi", "ci"),
                ("getServingLac", "lac"),
                ("getServingMcc", "mcc"),
                ("getServingMnc", "mnc"),
            ):
                if hasattr(net, method_name):
                    value = safe_call(getattr(net, method_name))
                    if ok_value(value):
                        data["serving"][key] = value

        if "raw" not in data:
            cells, source = safe_attr_call(net, ["getCellInfo", "currentCellInfo"])
            if ok_value(cells):
                data["raw"] = cells
                data["raw_source"] = source
                _fill_cell_serving_from_raw(data)
                _fill_cell_neighbors_from_raw(data)

        if not data["neighbors"]:
            for method_name, key in (
                ("getCi", "ci"),
                ("getLac", "lac"),
                ("getMcc", "mcc"),
                ("getMnc", "mnc"),
            ):
                if hasattr(net, method_name):
                    value = safe_call(getattr(net, method_name))
                    if ok_value(value):
                        data["neighbors"][key] = value
    return data


def gather_runtime_info(cfg, state):
    runtime = state.snapshot()
    runtime["gateway"] = {
        "url": getattr(cfg, "OPENCLAW_WS_URL", ""),
        "role": getattr(cfg, "OPENCLAW_ROLE", "node"),
        "device_auth_mode": getattr(cfg, "OPENCLAW_DEVICE_AUTH_MODE", "none"),
        "heartbeat_interval_sec": getattr(cfg, "HEARTBEAT_INTERVAL_SEC", 15),
        "telemetry_interval_sec": getattr(cfg, "TELEMETRY_INTERVAL_SEC", 60),
    }
    return runtime


def build_runtime_telemetry(cfg, state):
    runtime = gather_runtime_info(cfg, state)
    return {
        "device_id": cfg.DEVICE_ID,
        "node_id": state.node_id,
        "runtime": runtime,
        "ts": wall_time_ms(),
    }


def build_recommendations(sim_info, network_info, data_context):
    tips = []
    status = sim_info.get("status")
    if status not in (None, 1):
        tips.append("SIM 状态异常，优先检查卡状态、PIN 与卡槽接触。")
    registration = network_info.get("registration") or {}
    if registration and not registration.get("registered"):
        tips.append("模块尚未完成网络注册，建议检查天线、信号与运营商/APN。")
    if data_context.get("available") and data_context.get("state") != 1:
        tips.append("PDP 上下文未激活，建议检查 APN 配置或手动激活数据通道。")
    if not tips:
        tips.append("未发现明显异常，可继续验证 Gateway 连通与命令闭环。")
    return tips


def build_device_status(cfg, state, mask_sensitive):
    timings = {}
    started = utime.ticks_ms()
    modem_info = measure_step("gather_modem_info", timings, gather_modem_info, cfg, mask_sensitive)
    sim_info = measure_step("gather_sim_info", timings, gather_sim_info, mask_sensitive)
    network_info = measure_step("gather_network_info", timings, gather_network_info)
    data_context = measure_step("gather_data_context", timings, gather_data_context)
    runtime = measure_step("gather_runtime_info", timings, gather_runtime_info, cfg, state)
    cell = measure_step("gather_cell_info", timings, gather_cell_info, network_info)
    recommendations = measure_step(
        "build_recommendations",
        timings,
        build_recommendations,
        sim_info,
        network_info,
        data_context,
    )
    total_ms = utime.ticks_diff(utime.ticks_ms(), started)
    return {
        "device_id": cfg.DEVICE_ID,
        "node_id": state.node_id,
        "module_model": modem_info.get("module_model"),
        "firmware_version": modem_info.get("firmware_version") or modem_info.get("fw_version_config"),
        "imei": modem_info.get("imei"),
        "sim_inserted": sim_info.get("inserted"),
        "sim_ready": sim_info.get("ready"),
        "registration": network_info.get("registration"),
        "data_context": data_context,
        "signal": network_info.get("signal"),
        "operator": network_info.get("operator"),
        "runtime": runtime,
        "modem": modem_info,
        "sim": sim_info,
        "network": network_info,
        "cell": cell,
        "recommendations": recommendations,
        "probe_timings_ms": timings,
        "probe_duration_ms": total_ms,
        "ts": wall_time_ms(),
    }


def build_tool_catalog(entries):
    out = []
    for entry in entries:
        out.append({
            "tool": entry.get("name"),
            "aliases": entry.get("aliases") or [],
            "category": entry.get("category") or "misc",
            "summary": entry.get("summary") or "",
            "read_only": True,
            "source": "core",
        })
    return out
