#!/usr/bin/env python3
"""Провайдеры AI и декларативный план PrintForge (M3).

Провайдеры (AI-001):
- disabled: AI выключен, всё работает без него.
- scripted: детерминированный планировщик для разработки и приёмочных
  проверок конвейера (без LLM). Не является «AI-моделью» и так маркируется.
- openai: OpenAI-совместимый endpoint (PF_AI_BASE/PF_AI_KEY/PF_AI_MODEL),
  например локальный FreeLLMAPI (http://localhost:3001/v1) или Ollama.
"""
import hashlib
import json
import math
import os
import re
import uuid
import urllib.error
import urllib.parse
import urllib.request

AI_TIMEOUT_S = 30
MAX_PLAN_OPS = 20
MAX_RESPONSE_CHARS = 20000
OLLAMA_DEFAULT_BASE = "http://127.0.0.1:11434/v1"


def _environment_config():
    provider = os.environ.get("PF_AI_PROVIDER", "disabled").strip().lower()
    return {
        "provider": provider,
        "base_url": os.environ.get("PF_AI_BASE", "").strip().rstrip("/"),
        "model": os.environ.get("PF_AI_MODEL", "").strip(),
        "api_key": os.environ.get("PF_AI_KEY", ""),
    }


_PROVIDER_CONFIG = _environment_config()


def _is_loopback_url(url):
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"}


def _normalize_config(config, allow_scripted=False):
    normalized = {
        "provider": str(config.get("provider") or "").strip().lower(),
        "base_url": str(config.get("base_url") or "").strip().rstrip("/"),
        "model": str(config.get("model") or "").strip(),
        "api_key": str(config.get("api_key") or ""),
    }
    provider = normalized["provider"]
    if provider == "disabled":
        return normalized
    if provider == "scripted" and allow_scripted:
        normalized["base_url"] = ""
        normalized["model"] = "scripted-v1 (детерминированный, не LLM)"
        return normalized
    if provider not in {"ollama", "openai"}:
        raise ValueError("Неизвестный AI-провайдер.")
    if provider == "ollama" and not normalized["base_url"]:
        normalized["base_url"] = OLLAMA_DEFAULT_BASE
    parsed = urllib.parse.urlparse(normalized["base_url"])
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("URL AI-провайдера должен использовать http или https.")
    if parsed.username or parsed.password:
        raise ValueError(
            "Не помещайте логин или API key в URL. Используйте отдельное поле ключа.")
    if provider == "ollama" and not _is_loopback_url(normalized["base_url"]):
        raise ValueError(
            "Профиль Ollama разрешён только для локального endpoint (localhost/127.0.0.1).")
    if not normalized["model"]:
        raise ValueError("Укажите идентификатор модели.")
    return normalized


try:
    _PROVIDER_CONFIG = _normalize_config(_PROVIDER_CONFIG, allow_scripted=True)
except ValueError:
    _PROVIDER_CONFIG = _normalize_config({"provider": "disabled"})


def configure_provider(provider, base_url="", model="", api_key=None,
                       clear_api_key=False):
    global _PROVIDER_CONFIG
    if api_key and clear_api_key:
        raise ValueError("Нельзя одновременно сохранить и удалить API key.")
    candidate = dict(_PROVIDER_CONFIG)
    candidate.update({
        "provider": provider,
        "base_url": base_url,
        "model": model,
    })
    if clear_api_key:
        candidate["api_key"] = ""
    elif api_key:
        candidate["api_key"] = api_key
    _PROVIDER_CONFIG = _normalize_config(candidate)
    return provider_info()


def provider_info():
    config = dict(_PROVIDER_CONFIG)
    p = config["provider"]
    return {
        "provider": p,
        "available": p != "disabled",
        "scripted": p == "scripted",
        "model": config["model"],
        "base_url": config["base_url"],
        "has_api_key": bool(config["api_key"]),
        "secret_storage": "session",
        "local_endpoint": _is_loopback_url(config["base_url"]),
        "capabilities": {
            "structured_output": p == "ollama",
            "json_object": p in {"ollama", "openai"},
            "tools": False,
            "images": False,
            "context_limit": 4096 if p in {"ollama", "openai"} else 0,
        },
    }


def _parse_number(text, default=None):
    m = re.search(r"(\d+(?:[.,]\d+)?)", text)
    return float(m.group(1).replace(",", ".")) if m else default


def scripted_plan(text, doc):
    """Детерминированный планировщик для проверки конвейера.
    Покрывает сценарии AC-10: пластина и шайба по размерам; изменение
    параметра; неоднозначный запрос → уточнение/явное предположение."""
    t = text.lower()
    plan = {
        "schema_version": 1,
        "document_id": doc.doc_id,
        "document_instance_id": doc.document_instance_id,
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
    if "пластин" in t:
        dimensions = [float(value.replace(",", ".")) for value in re.findall(
            r"\d+(?:[.,]\d+)?", t)]
        length = dimensions[0] if len(dimensions) > 0 else 80
        width = dimensions[1] if len(dimensions) > 1 else 40
        height_match = re.search(r"толщин\w*\s*(\d+(?:[.,]\d+)?)", t)
        hole_match = re.search(r"отверсти\w*\s*(\d+(?:[.,]\d+)?)\s*мм", t)
        height = (float(height_match.group(1).replace(",", "."))
                  if height_match else (dimensions[2] if len(dimensions) > 2 else 6))
        hole_diameter = (float(hole_match.group(1).replace(",", "."))
                         if hole_match else 4)
        plan["operations"] = [{
            "command_id": "part.create.from_template",
            "target_id": None,
            "parameters": {
                "template": "plate_with_holes",
                "params": {
                    "length": length,
                    "width": width,
                    "height": height,
                    "hole_diameter": hole_diameter,
                },
            },
        }]
        plan["summary"] = (
            f"Создать пластину {length:g} × {width:g} × {height:g} мм "
            f"с отверстиями Ø{hole_diameter:g} мм")
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


def http_chat(messages, want_json, json_schema=None):
    config = dict(_PROVIDER_CONFIG)
    if config["provider"] not in {"ollama", "openai"}:
        raise RuntimeError(json.dumps({
            "code": "ai_provider_invalid",
            "message": "Для сетевого запроса не настроен AI-провайдер.",
            "detail": ""}, ensure_ascii=False))
    base = config["base_url"]
    key = config["api_key"]
    model = config["model"]
    body = {"model": model, "messages": messages, "temperature": 0}
    if config["provider"] == "ollama":
        body["reasoning_effort"] = "none"
    if json_schema is not None and config["provider"] == "ollama":
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "printforge_plan",
                "strict": True,
                "schema": json_schema,
            },
        }
    elif want_json:
        body["response_format"] = {"type": "json_object"}
    headers = {"content-type": "application/json"}
    if key:
        headers["authorization"] = f"Bearer {key}"
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(body).encode(),
        headers=headers)
    with urllib.request.urlopen(req, timeout=AI_TIMEOUT_S) as response:
        raw = response.read(MAX_RESPONSE_CHARS + 1)
    if len(raw) > MAX_RESPONSE_CHARS:
        raise ValueError("Ответ AI превышает допустимый размер.")
    data = json.loads(raw)
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError("Провайдер вернул неверный формат ответа.") from error
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Провайдер вернул пустой ответ.")
    return content


def test_connection():
    config = dict(_PROVIDER_CONFIG)
    if config["provider"] == "disabled":
        raise ValueError("AI-помощник выключен.")
    if config["provider"] == "scripted":
        return {
            "ok": True,
            "message": "Детерминированный планировщик доступен локально; сетевой запрос не выполнялся.",
            "model_found": True,
        }
    headers = {}
    if config["api_key"]:
        headers["authorization"] = f"Bearer {config['api_key']}"
    request = urllib.request.Request(config["base_url"] + "/models", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read(MAX_RESPONSE_CHARS + 1))
    except urllib.error.HTTPError as error:
        raise ValueError(
            f"Провайдер вернул HTTP {error.code} при проверке /models.") from error
    except urllib.error.URLError as error:
        raise ValueError(f"Провайдер AI недоступен: {error.reason}") from error
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise ValueError("Провайдер вернул некорректный список /models.")
    models = [item["id"] for item in data["data"]
              if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip()]
    model_found = config["model"] in models
    if model_found:
        message = f"Соединение установлено. Модель «{config['model']}» доступна."
    else:
        message = (f"Соединение установлено, но модель «{config['model']}» "
                   "отсутствует в ответе /models.")
    return {
        "ok": True,
        "message": message,
        "model_found": model_found,
        "models": models,
    }


def ai_chat(messages, want_json=False):
    p = _PROVIDER_CONFIG["provider"]
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


def _raise_if_cancelled(is_cancelled):
    if is_cancelled is not None and is_cancelled():
        raise RuntimeError(json.dumps({
            "code": "ai_cancelled",
            "message": "AI-запрос отменён пользователем.",
            "detail": "",
        }, ensure_ascii=False))


def ai_plan(text, doc, transaction_preview, is_cancelled=None):
    """Полный цикл AI-005: запрос → план → валидация → preview на копии."""
    _raise_if_cancelled(is_cancelled)
    p = _PROVIDER_CONFIG["provider"]
    repair_count = 0
    if p == "disabled":
        raise RuntimeError(json.dumps({
            "code": "ai_disabled",
            "message": "AI-помощник выключен в настройках.",
            "detail": ""}, ensure_ascii=False))
    if p == "scripted":
        plan = scripted_plan(text, doc)
    else:
        sys_prompt = system_prompt(doc)
        schema = plan_json_schema(doc, text)
        raw = http_chat([
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": text}], want_json=True,
            json_schema=schema)
        _raise_if_cancelled(is_cancelled)
        plan, validation_error = _parse_and_validate(raw, doc)
        if validation_error:
            # Ровно одна автоматическая попытка исправления JSON или схемы.
            repair_count = 1
            raw2 = http_chat([
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": text},
                {"role": "assistant", "content": raw},
                {"role": "user", "content": (
                    "Ответ не прошёл проверку JSON-схемы: "
                    f"{validation_error['message']} Исправь, ответь только JSON.")},
                ],
                want_json=True, json_schema=schema)
            _raise_if_cancelled(is_cancelled)
            plan, validation_error = _parse_and_validate(raw2, doc)
            if validation_error:
                raise RuntimeError(json.dumps(validation_error, ensure_ascii=False))
    err = validate_plan(plan, doc)
    if err:
        raise RuntimeError(json.dumps(err, ensure_ascii=False))
    _raise_if_cancelled(is_cancelled)
    digest = plan_hash(plan)
    action_id = str(uuid.uuid4())
    preview = None
    if plan["operations"]:
        preview = transaction_preview(
            plan["operations"], plan["base_revision"], digest)
    return {
        "plan": plan,
        "preview": preview,
        "plan_hash": digest,
        "action_id": action_id,
        "repair_count": repair_count,
    }


def _parse_and_validate(raw, doc):
    try:
        plan = json.loads(_extract_json(raw))
    except (json.JSONDecodeError, ValueError):
        return None, {
            "code": "plan_invalid",
            "message": "Ответ AI не является валидным JSON-планом.",
            "detail": "",
        }
    return plan, validate_plan(plan, doc)


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
    return json.dumps({"document_id": doc.doc_id,
                       "document_instance_id": doc.document_instance_id,
                       "revision": doc.revision,
                       "units": "mm", "parts": parts}, ensure_ascii=False)


def system_prompt(doc):
    if doc.parts:
        existing = "; ".join(
            f'{part["part_id"]} ({part["template"]}): '
            + ", ".join(sorted(part.get("params", {})))
            for part in doc.parts)
        document_rule = (
            "Документ уже содержит детали: " + existing + ". "
            "Запросы «измени», «установи», «увеличь» и «сделай [существующую деталь] "
            "размером ...» означают parameter.set. part.create.from_template допустим "
            "только при явном запросе создать или добавить новую деталь. "
        )
    else:
        document_rule = (
            "Документ пуст: для явного запроса создать деталь используй "
            "part.create.from_template. "
        )
    return (
        "Ты планировщик CAD PrintForge. Отвечай ТОЛЬКО JSON по переданной схеме. "
        "Используй только эти операции и точные идентификаторы:\n"
        "1. part.create.from_template: target_id=null, parameters={template, params}. "
        "Допустимые шаблоны и параметры: "
        "box {length, width, height}; "
        "cylinder {diameter, height}; "
        "sphere {diameter}; "
        "washer {outer_diameter, inner_diameter, height}; "
        "plate_with_holes {length, width, height, hole_diameter, hole_offset}; "
        "bracket_l {a_length, a_width, a_thickness, b_height}; "
        "case_with_lid {length, width, height, wall, bottom, gap, lid_thickness, "
        "lip_height, lip_wall}. В params указывай только размеры, явно названные "
        "пользователем; остальные поля не выдумывай — backend применит defaults.\n"
        "2. parameter.set: target_id — существующий part_id, "
        "parameters={name, value}; name обязан уже существовать в params этой детали. "
        "Если пользователь меняет существующую деталь, используй parameter.set, "
        "не создавай новую деталь.\n"
        "3. op.fillet: target_id — существующий part_id, parameters={radius, edge_ref}; "
        "edge_ref должен быть точным объектом из контекста. Если edge_ref в контексте нет, "
        "задай вопрос и не создавай операцию.\n"
        "Не выдумывай template, parameter name, part_id или edge_ref. "
        "Если не хватает размера либо запрос неоднозначен (например, «побольше», "
        "«покрепче», «добавь отверстие»), оставь operations пустым и заполни questions, "
        "либо укажи явное измеримое предположение в assumptions. "
        "Никогда не исполняй код, не читай файлы и не устанавливай расширения. "
        "Все размеры только в мм. Никакого Markdown, только данные.\n"
        + document_rule + "Документ: "
        + doc_summary(doc)
    )


def _request_operation_scope(doc, text):
    if text is None:
        return None, False, False
    normalized = text.lower().replace("ё", "е")
    unsafe_or_invalid = (
        re.search(r"(^|\D)-\s*\d", normalized)
        or re.search(r"\bnan\b", normalized)
        or any(marker in normalized for marker in (
            "python", "/etc/", "прочитай файл", "открой файл",
            "установи расширение", "запусти код")))
    if unsafe_or_invalid:
        return set(), False, True

    template_markers = {
        "box": ("параллелеп", "куб", "брусок"),
        "cylinder": ("цилиндр",),
        "sphere": ("сфер", "шар"),
        "washer": ("шайб", "втулк"),
        "plate_with_holes": ("пластин",),
        "bracket_l": ("кроншт",),
        "case_with_lid": ("корпус", "крышк"),
    }
    requested_templates = {
        template for template, markers in template_markers.items()
        if any(marker in normalized for marker in markers)
    }
    scope = set()
    explicit_create = not doc.parts or "созд" in normalized or "добавь деталь" in normalized
    if explicit_create:
        scope.update(("create", template) for template in requested_templates)

    parameter_markers = {
        "length": ("длин",),
        "width": ("ширин",),
        "height": ("толщин", "высот"),
        "diameter": ("диаметр",),
        "hole_diameter": ("диаметр отверст", "отверсти", "побольш"),
        "hole_offset": ("смещен", "отступ"),
        "outer_diameter": ("наружн",),
        "inner_diameter": ("внутрен",),
        "a_length": ("длин",),
        "a_width": ("ширин",),
        "a_thickness": ("толщин",),
        "b_height": ("высот", "стойк"),
        "wall": ("стенк",),
        "bottom": ("дн",),
        "gap": ("зазор",),
        "lid_thickness": ("толщин крыш",),
        "lip_height": ("высот бортик",),
        "lip_wall": ("толщин бортик",),
    }
    for part in doc.parts:
        for name in part.get("params", {}):
            if any(marker in normalized for marker in parameter_markers.get(name, ())):
                scope.add(("parameter", part["part_id"], name))
        if "скруг" in normalized or "радиус" in normalized:
            scope.add(("fillet", part["part_id"]))

    requires_assumption = "побольш" in normalized and bool(scope)
    requires_question = not scope
    return scope, requires_assumption, requires_question


def plan_json_schema(doc, text=None):
    create_variants = {}
    parameter_variants = {}
    fillet_variants = {}
    number = {"type": "number", "exclusiveMinimum": 0}
    for template, parameter_names in TEMPLATE_PARAMS.items():
        create_variants[template] = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "command_id": {"const": "part.create.from_template"},
                "target_id": {"type": "null"},
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "template": {"const": template},
                        "params": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                name: number for name in parameter_names
                            },
                        },
                    },
                    "required": ["template", "params"],
                },
            },
            "required": ["command_id", "target_id", "parameters"],
        }
    for part in doc.parts:
        for name in sorted(part.get("params", {})):
            parameter_variants[(part["part_id"], name)] = {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "command_id": {"const": "parameter.set"},
                    "target_id": {"const": part["part_id"]},
                    "parameters": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "name": {"const": name},
                            "value": number,
                        },
                        "required": ["name", "value"],
                    },
                },
                "required": ["command_id", "target_id", "parameters"],
            }
        fillet_variants[part["part_id"]] = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "command_id": {"const": "op.fillet"},
                "target_id": {"const": part["part_id"]},
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "radius": number,
                        "edge_ref": {"type": "object"},
                    },
                    "required": ["radius", "edge_ref"],
                },
            },
            "required": ["command_id", "target_id", "parameters"],
        }

    scope, requires_assumption, requires_question = _request_operation_scope(doc, text)
    if scope is None:
        operation_variants = [
            *create_variants.values(),
            *parameter_variants.values(),
            *fillet_variants.values(),
        ]
    else:
        operation_variants = []
        for item in sorted(scope):
            if item[0] == "create" and item[1] in create_variants:
                operation_variants.append(create_variants[item[1]])
            elif item[0] == "parameter" and (item[1], item[2]) in parameter_variants:
                operation_variants.append(parameter_variants[(item[1], item[2])])
            elif item[0] == "fillet" and item[1] in fillet_variants:
                operation_variants.append(fillet_variants[item[1]])

    assumptions_schema = {"type": "array", "items": {"type": "string"}}
    questions_schema = {"type": "array", "items": {"type": "string"}}
    operations_schema = {"type": "array", "maxItems": MAX_PLAN_OPS}
    if operation_variants:
        operations_schema["items"] = {"oneOf": operation_variants}
    else:
        operations_schema["maxItems"] = 0
    if requires_assumption:
        assumptions_schema["minItems"] = 1
    if requires_question:
        questions_schema["minItems"] = 1
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "integer", "const": 1},
            "document_id": {"const": doc.doc_id},
            "document_instance_id": {"const": doc.document_instance_id},
            "base_revision": {"type": "integer", "const": doc.revision},
            "units": {"type": "string", "const": "mm"},
            "assumptions": assumptions_schema,
            "questions": questions_schema,
            "operations": operations_schema,
            "summary": {"type": "string"},
        },
        "required": ["schema_version", "document_id", "document_instance_id",
                     "base_revision", "units",
                     "assumptions", "questions", "operations", "summary"],
    }


def plan_hash(plan):
    identity = {
        "schema_version": plan.get("schema_version"),
        "document_id": plan.get("document_id"),
        "document_instance_id": plan.get("document_instance_id"),
        "base_revision": plan.get("base_revision"),
        "units": plan.get("units"),
        "operations": plan.get("operations"),
    }
    canonical = json.dumps(
        identity, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


ALLOWED_COMMANDS = {"part.create.from_template", "parameter.set", "op.fillet"}
TEMPLATES = {"box", "cylinder", "sphere", "plate_with_holes", "washer", "bracket_l", "case_with_lid"}
TEMPLATE_PARAMS = {
    "box": ("length", "width", "height"),
    "cylinder": ("diameter", "height"),
    "sphere": ("diameter",),
    "washer": ("outer_diameter", "inner_diameter", "height"),
    "plate_with_holes": (
        "length", "width", "height", "hole_diameter", "hole_offset"),
    "bracket_l": ("a_length", "a_width", "a_thickness", "b_height"),
    "case_with_lid": (
        "length", "width", "height", "wall", "bottom", "gap",
        "lid_thickness", "lip_height", "lip_wall"),
}
SIGNED_PARAMS = {"length", "width", "height", "diameter", "hole_diameter", "hole_offset",
                 "outer_diameter", "inner_diameter", "a_length", "a_width",
                 "a_thickness", "b_height", "wall", "bottom", "gap",
                 "lid_thickness", "lip_height", "lip_wall", "radius"}


def validate_plan(plan, doc):
    def err(code, message):
        return {"code": code, "message": message, "detail": ""}
    if not isinstance(plan, dict):
        return err("plan_invalid", "Ответ AI не является планом (ожидался JSON-объект).")
    required = {
        "schema_version", "document_id", "document_instance_id", "base_revision",
        "units", "assumptions", "questions", "operations", "summary",
    }
    missing = sorted(required - set(plan))
    unknown = sorted(set(plan) - required)
    if missing:
        return err("plan_invalid", f"В плане отсутствуют обязательные поля: {', '.join(missing)}.")
    if unknown:
        return err("plan_invalid", f"В плане есть запрещённые поля: {', '.join(unknown)}.")
    if (not isinstance(plan["assumptions"], list)
            or not all(isinstance(item, str) for item in plan["assumptions"])):
        return err("plan_invalid", "Поле assumptions должно быть массивом строк.")
    if (not isinstance(plan["questions"], list)
            or not all(isinstance(item, str) for item in plan["questions"])):
        return err("plan_invalid", "Поле questions должно быть массивом строк.")
    if not isinstance(plan["summary"], str):
        return err("plan_invalid", "Поле summary должно быть строкой.")
    if plan.get("schema_version") != 1:
        return err("plan_invalid", "Неизвестная версия схемы плана.")
    if plan.get("units") != "mm":
        return err("plan_invalid", "План не в миллиметрах — не применяется.")
    if plan.get("document_id") != doc.doc_id:
        return err("plan_stale", "План относится к другому документу.")
    if plan.get("document_instance_id") != doc.document_instance_id:
        return err("plan_stale", "План относится к другому открытию документа.")
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
    parts_by_id = {p["part_id"]: p for p in doc.parts}
    for i, op in enumerate(ops, 1):
        if not isinstance(op, dict) or "command_id" not in op:
            return err("plan_invalid", f"Операция {i}: нет command_id.")
        operation_fields = {"command_id", "target_id", "parameters"}
        if set(op) != operation_fields:
            return err("plan_invalid", f"Операция {i}: неверный набор полей.")
        if op["target_id"] is not None and not isinstance(op["target_id"], str):
            return err("plan_invalid", f"Операция {i}: target_id должен быть строкой или null.")
        cid = op["command_id"]
        if cid not in ALLOWED_COMMANDS:
            return err("plan_forbidden",
                       f"Операция {i}: команда «{cid}» не разрешена для AI.")
        params = op.get("parameters")
        if not isinstance(params, dict):
            return err("plan_invalid", f"Операция {i}: нет параметров.")
        if cid == "part.create.from_template":
            if set(params) - {"template", "params"}:
                return err("plan_invalid", f"Операция {i}: неизвестные параметры шаблона.")
            if params.get("template") not in TEMPLATES:
                return err("plan_invalid", f"Операция {i}: неизвестный шаблон.")
            template_params = params.get("params") or {}
            if not isinstance(template_params, dict):
                return err("plan_invalid", f"Операция {i}: params должен быть объектом.")
            for k, v in template_params.items():
                bad = _check_number(k, v)
                if bad:
                    return err("plan_invalid", f"Операция {i}: {bad}")
        elif cid == "parameter.set":
            tid = op.get("target_id")
            if tid not in part_ids:
                return err("plan_invalid",
                           f"Операция {i}: деталь «{tid}» не существует в документе.")
            name, value = params.get("name"), params.get("value")
            if set(params) != {"name", "value"} or not isinstance(name, str):
                return err("plan_invalid", f"Операция {i}: неверные параметры parameter.set.")
            if name not in parts_by_id[tid].get("params", {}):
                return err("plan_invalid", f"Операция {i}: параметр «{name}» не существует.")
            bad = _check_number(name, value)
            if bad:
                return err("plan_invalid", f"Операция {i}: {bad}")
        elif cid == "op.fillet":
            if set(params) - {"radius", "edge_ref"}:
                return err("plan_invalid", f"Операция {i}: неизвестные параметры скругления.")
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
