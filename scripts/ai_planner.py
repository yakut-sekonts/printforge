#!/usr/bin/env python3
"""Провайдеры AI и декларативный план PrintForge (M3).

Провайдеры (AI-001):
- disabled: AI выключен, всё работает без него.
- scripted: детерминированный планировщик для разработки и приёмочных
  проверок конвейера (без LLM). Не является «AI-моделью» и так маркируется.
- openai: OpenAI-совместимый endpoint (PF_AI_BASE/PF_AI_KEY/PF_AI_MODEL),
  например локальный FreeLLMAPI (http://localhost:3001/v1) или Ollama.
"""
import json
import math
import os
import re
import urllib.request

AI_TIMEOUT_S = 30
MAX_PLAN_OPS = 20
MAX_RESPONSE_CHARS = 20000


def provider_info():
    p = os.environ.get("PF_AI_PROVIDER", "scripted")
    return {
        "provider": p,
        "available": p != "disabled",
        "scripted": p == "scripted",
        "model": os.environ.get("PF_AI_MODEL", "-") if p != "scripted" else "scripted-v1 (детерминированный, не LLM)",
        "base_url": os.environ.get("PF_AI_BASE", "") if p == "openai" else "",
    }


def _parse_number(text, default=None):
    m = re.search(r"(\d+(?:[.,]\d+)?)", text)
    return float(m.group(1).replace(",", ".")) if m else default


def scripted_plan(text, doc):
    """Детерминированный планировщик для проверки конвейера.
    Покрывает сценарии AC-10: шайба по размерам; изменение параметра;
    неоднозначный запрос → уточнение/явное предположение."""
    t = text.lower()
    plan = {
        "schema_version": 1,
        "document_id": doc.doc_id,
        "base_revision": doc.revision,
        "units": "mm",
        "assumptions": [],
        "questions": [],
        "operations": [],
        "summary": "",
    }
    if "шайб" in t or "втулк" in t:
        od = _parse_number(t.split("наружн")[-1] if "наружн" in t else t, 20)
        id_ = _parse_number(t.split("внутрен")[-1] if "внутрен" in t else "6", 6)
        h = _parse_number(t.split("высот")[-1] if "высот" in t else "4", 4)
        plan["operations"] = [{
            "command_id": "part.create.from_template",
            "target_id": None,
            "parameters": {"template": "washer",
                           "params": {"outer_diameter": od,
                                      "inner_diameter": id_, "height": h}},
        }]
        plan["summary"] = (f"Создать шайбу: наружный диаметр {od:g} мм, "
                           f"внутренний {id_:g} мм, высота {h:g} мм")
        return plan
    m = re.search(r"длин\w*\s+(?:на|до|=)?\s*(\d+(?:[.,]\d+)?)", t)
    if m and doc.parts:
        value = float(m.group(1).replace(",", "."))
        part = doc.parts[0]
        name = "length" if "length" in part["params"] else next(iter(part["params"]))
        plan["operations"] = [{
            "command_id": "parameter.set",
            "target_id": part["part_id"],
            "parameters": {"name": name, "value": value},
        }]
        plan["summary"] = f"Изменить параметр «{name}» на {value:g} мм"
        return plan
    if "отверсти" in t and "побольше" in t:
        part = doc.parts[0] if doc.parts else None
        cur = part["params"].get("hole_diameter") if part else None
        if cur is None:
            plan["questions"] = ["У какой детали увеличить отверстие и до какого диаметра?"]
            plan["summary"] = "Нужно уточнение: деталь и диаметр не указаны"
            return plan
        new_d = round(cur * 1.5, 1)
        plan["assumptions"] = [
            f"«Побольше» трактую как +50%: диаметр {cur:g} → {new_d:g} мм (можно изменить перед применением)"]
        plan["operations"] = [{
            "command_id": "parameter.set",
            "target_id": part["part_id"],
            "parameters": {"name": "hole_diameter", "value": new_d},
        }]
        plan["summary"] = f"Увеличить отверстие до {new_d:g} мм"
        return plan
    plan["questions"] = ["Не понял запрос. Опишите деталь размерами, "
                         "например: «шайба 20 на 6, высота 4»."]
    plan["summary"] = "Запрос не распознан — нужны размеры"
    return plan


def http_chat(messages, want_json):
    base = os.environ.get("PF_AI_BASE", "").rstrip("/")
    key = os.environ.get("PF_AI_KEY", "")
    model = os.environ.get("PF_AI_MODEL", "auto")
    body = {"model": model, "messages": messages, "temperature": 0}
    if want_json:
        body["response_format"] = {"type": "json_object"}
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json",
                 "authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=AI_TIMEOUT_S) as r:
        data = json.loads(r.read(MAX_RESPONSE_CHARS + 1))
    return data["choices"][0]["message"]["content"]


def ai_chat(messages, want_json=False):
    p = os.environ.get("PF_AI_PROVIDER", "scripted")
    if p == "disabled":
        raise RuntimeError(json.dumps({
            "code": "ai_disabled",
            "message": "AI-помощник выключен в настройках. Справочник и все инструменты работают без него.",
            "detail": ""}, ensure_ascii=False))
    if p == "scripted":
        # scripted работает только как планировщик, не чат
        raise RuntimeError(json.dumps({
            "code": "ai_scripted_only",
            "message": "Включён детерминированный планировщик (не LLM): используйте «Предложить план».",
            "detail": ""}, ensure_ascii=False))
    return http_chat(messages, want_json)


def ai_plan(text, doc, transaction_preview):
    """Полный цикл AI-005: запрос → план → валидация → preview на копии."""
    p = os.environ.get("PF_AI_PROVIDER", "scripted")
    if p == "disabled":
        raise RuntimeError(json.dumps({
            "code": "ai_disabled",
            "message": "AI-помощник выключен в настройках.",
            "detail": ""}, ensure_ascii=False))
    if p == "scripted":
        plan = scripted_plan(text, doc)
    else:
        summary = doc_summary(doc)
        sys_prompt = (
            "Ты планировщик CAD PrintForge. Отвечай ТОЛЬКО JSON по схеме: "
            "{schema_version:1, document_id, base_revision, units:\"mm\", "
            "assumptions:[], questions:[], operations:[{command_id, target_id, "
            "parameters}], summary}. Разрешённые command_id: "
            "part.create.from_template {template, params}, "
            "parameter.set {name, value}, op.fillet {radius, edge_ref}. "
            "Никакого кода, только данные.\nДокумент: " + summary)
        raw = http_chat([
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": text}], want_json=True)
        try:
            plan = json.loads(_extract_json(raw))
        except (json.JSONDecodeError, ValueError):
            # одна автоматическая попытка исправления (AI-006)
            raw2 = http_chat([
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": text},
                {"role": "assistant", "content": raw},
                {"role": "user", "content": "Это не валидный JSON по схеме. Исправь, ответь только JSON."}],
                want_json=True)
            plan = json.loads(_extract_json(raw2))
    err = validate_plan(plan, doc)
    if err:
        raise RuntimeError(json.dumps(err, ensure_ascii=False))
    preview = transaction_preview(plan["operations"], plan["base_revision"])
    return {"plan": plan, "preview": preview}


def _extract_json(raw):
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no json")
    return raw[start:end + 1]


def doc_summary(doc):
    parts = [{"part_id": p["part_id"], "template": p["template"],
              "params": p["params"]} for p in doc.parts]
    return json.dumps({"document_id": doc.doc_id, "revision": doc.revision,
                       "units": "mm", "parts": parts}, ensure_ascii=False)


ALLOWED_COMMANDS = {"part.create.from_template", "parameter.set", "op.fillet"}
TEMPLATES = {"plate_with_holes", "washer", "bracket_l", "case_with_lid"}
SIGNED_PARAMS = {"length", "width", "height", "hole_diameter", "hole_offset",
                 "outer_diameter", "inner_diameter", "a_length", "a_width",
                 "a_thickness", "b_height", "wall", "bottom", "gap",
                 "lid_thickness", "lip_height", "lip_wall", "radius"}


def validate_plan(plan, doc):
    def err(code, message):
        return {"code": code, "message": message, "detail": ""}
    if not isinstance(plan, dict):
        return err("plan_invalid", "Ответ AI не является планом (ожидался JSON-объект).")
    if plan.get("schema_version") != 1:
        return err("plan_invalid", "Неизвестная версия схемы плана.")
    if plan.get("units") != "mm":
        return err("plan_invalid", "План не в миллиметрах — не применяется.")
    if plan.get("document_id") != doc.doc_id:
        return err("plan_stale", "План относится к другому документу.")
    if plan.get("base_revision") != doc.revision:
        return err("plan_stale",
                   "Документ изменился, пока формировался план. Предложение устарело — пересчитайте.")
    ops = plan.get("operations")
    if not isinstance(ops, list) or not ops:
        if plan.get("questions"):
            return None  # уточнение без операций — законный ответ
        return err("plan_invalid", "В плане нет операций.")
    if len(ops) > MAX_PLAN_OPS:
        return err("plan_invalid", f"В плане больше {MAX_PLAN_OPS} операций — отклонён.")
    part_ids = {p["part_id"] for p in doc.parts}
    for i, op in enumerate(ops, 1):
        if not isinstance(op, dict) or "command_id" not in op:
            return err("plan_invalid", f"Операция {i}: нет command_id.")
        cid = op["command_id"]
        if cid not in ALLOWED_COMMANDS:
            return err("plan_forbidden",
                       f"Операция {i}: команда «{cid}» не разрешена для AI.")
        params = op.get("parameters")
        if not isinstance(params, dict):
            return err("plan_invalid", f"Операция {i}: нет параметров.")
        if cid == "part.create.from_template":
            if params.get("template") not in TEMPLATES:
                return err("plan_invalid", f"Операция {i}: неизвестный шаблон.")
            for k, v in (params.get("params") or {}).items():
                bad = _check_number(k, v)
                if bad:
                    return err("plan_invalid", f"Операция {i}: {bad}")
        elif cid == "parameter.set":
            tid = op.get("target_id")
            if tid not in part_ids:
                return err("plan_invalid",
                           f"Операция {i}: деталь «{tid}» не существует в документе.")
            name, value = params.get("name"), params.get("value")
            bad = _check_number(name, value)
            if bad:
                return err("plan_invalid", f"Операция {i}: {bad}")
        elif cid == "op.fillet":
            bad = _check_number("radius", params.get("radius"))
            if bad:
                return err("plan_invalid", f"Операция {i}: {bad}")
            if tid := op.get("target_id"):
                if tid not in part_ids:
                    return err("plan_invalid", f"Операция {i}: деталь «{tid}» не существует.")
    return None


def _check_number(name, value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return f"параметр «{name}» не число."
    if not math.isfinite(value):
        return f"параметр «{name}» не конечное число."
    if name in SIGNED_PARAMS and value <= 0:
        return f"параметр «{name}» должен быть положительным (получено {value:g})."
    if name in SIGNED_PARAMS and value > 10000:
        return f"параметр «{name}» вне разумного диапазона ({value:g} мм)."
    return None
