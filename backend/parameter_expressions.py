import copy
import math
import re


ALIASES = {
    "длина": "length", "ширина": "width", "высота": "height", "диаметр": "diameter",
    "наружный_диаметр": "outer_diameter", "внутренний_диаметр": "inner_diameter",
    "диаметр_отверстия": "hole_diameter", "отступ": "hole_offset",
    "отступ_отверстий": "hole_offset", "стенка": "wall", "дно": "bottom",
    "зазор": "gap", "толщина_крышки": "lid_thickness", "высота_бортика": "lip_height",
    "стенка_бортика": "lip_wall", "толщина_бортика": "lip_wall",
    "длина_полки": "a_length", "ширина_полки": "a_width",
    "толщина_полки": "a_thickness", "высота_стойки": "b_height",
}
MINIMUMS = {
    "box": {"length": 0.1, "width": 0.1, "height": 0.1},
    "cylinder": {"diameter": 0.1, "height": 0.1},
    "sphere": {"diameter": 0.1},
    "plate_with_holes": {"length": 0.1, "width": 0.1, "height": 0.1, "hole_diameter": 0, "hole_offset": 0},
    "washer": {"outer_diameter": 0.1, "inner_diameter": 0, "height": 0.1},
    "bracket_l": {"a_length": 0.1, "a_width": 0.1, "a_thickness": 0.1, "b_height": 0.1},
    "case_with_lid": {"length": 1, "width": 1, "height": 1, "wall": 0.4, "bottom": 0.4, "gap": 0, "lid_thickness": 0.4, "lip_height": 0, "lip_wall": 0.4},
}
TOKEN = re.compile(r"\s*(?:(\d+(?:\.\d*)?|\.\d+)|([a-zA-Z_а-яА-ЯёЁ][\wа-яА-ЯёЁ]*)|([+*/()\-]))")


def canonical_name(name):
    if not isinstance(name, str):
        raise ValueError("Имя параметра должно быть строкой.")
    return ALIASES.get(name.casefold(), name)


class Parser:
    def __init__(self, source, resolve):
        if not isinstance(source, str) or not source.strip() or len(source) > 2048:
            raise ValueError("Выражение пустое или слишком длинное.")
        self.tokens = []
        self.position = 0
        self.depth = 0
        self.resolve = resolve
        normalized = source.replace(",", ".").strip()
        offset = 0
        while offset < len(normalized):
            match = TOKEN.match(normalized, offset)
            if match is None:
                raise ValueError(f"Недопустимый символ «{normalized[offset]}».")
            number, name, operator = match.groups()
            if number:
                token = ("number", float(number))
            elif name:
                token = ("name", name)
            else:
                token = ("operator", operator)
            self.tokens.append(token)
            offset = match.end()
        if len(self.tokens) > 512:
            raise ValueError("Выражение слишком сложное.")

    def eat(self, operator):
        if self.position < len(self.tokens) and self.tokens[self.position] == ("operator", operator):
            self.position += 1
            return True
        return False

    def expression(self):
        value = self.term()
        while True:
            if self.eat("+"):
                value += self.term()
            elif self.eat("-"):
                value -= self.term()
            else:
                return value

    def term(self):
        value = self.factor()
        while True:
            if self.eat("*"):
                value *= self.factor()
            elif self.eat("/"):
                denominator = self.factor()
                if denominator == 0:
                    raise ValueError("Деление на ноль.")
                value /= denominator
            else:
                return value

    def factor(self):
        self.depth += 1
        try:
            if self.depth > 64:
                raise ValueError("Выражение слишком сложное.")
            if self.eat("-"):
                return -self.factor()
            if self.eat("+"):
                return self.factor()
            if self.eat("("):
                value = self.expression()
                if not self.eat(")"):
                    raise ValueError("Нет закрывающей скобки.")
                return value
            if self.position >= len(self.tokens):
                raise ValueError("Выражение обрывается.")
            kind, value = self.tokens[self.position]
            self.position += 1
            if kind == "number":
                return value
            if kind == "name":
                return self.resolve(canonical_name(value))
            raise ValueError(f"Неожиданный символ «{value}».")
        finally:
            self.depth -= 1

    def evaluate(self):
        value = self.expression()
        if self.position != len(self.tokens):
            raise ValueError("Лишние символы в конце выражения.")
        if not math.isfinite(value):
            raise ValueError("Результат не является конечным числом.")
        return value


def resolve_parts(parts, expressions, defaults):
    if not isinstance(parts, list) or not isinstance(expressions, dict):
        raise ValueError("Параметры документа или выражения повреждены.")
    resolved = copy.deepcopy(parts)
    by_id = {}
    for part in resolved:
        if not isinstance(part, dict) or part.get("template") not in defaults:
            raise ValueError("Неизвестный шаблон в параметрах документа.")
        identifier = part.get("part_id")
        if not isinstance(identifier, str) or not identifier or identifier in by_id:
            raise ValueError("Идентификаторы деталей повреждены или повторяются.")
        parameters = part.get("params") or {}
        if not isinstance(parameters, dict) or set(parameters) - defaults[part["template"]].keys():
            raise ValueError("Документ содержит неизвестный параметр шаблона.")
        part["params"] = {**defaults[part["template"]], **parameters}
        by_id[identifier] = part
    normalized_expressions = {}
    if any(not isinstance(key, str) for key in expressions):
        raise ValueError("Ключ выражения должен быть строкой.")
    for original_key in sorted(expressions, key=lambda key: "." in key):
        key, source = original_key, expressions[original_key]
        if "." not in key and by_id:
            key = f"{next(iter(by_id))}.{key}"
        identifier, separator, name = key.rpartition(".")
        name = canonical_name(name)
        if not separator or identifier not in by_id or name not in by_id[identifier]["params"]:
            raise ValueError(f"Выражение ссылается на неизвестный параметр «{key}».")
        if not isinstance(source, str) or not source.strip():
            raise ValueError(f"Выражение параметра «{key}» пустое.")
        normalized_expressions[f"{identifier}.{name}"] = source
    for identifier, part in by_id.items():
        parameters = part["params"]
        completed = set()
        pending = set()

        def resolve(name):
            if name not in parameters:
                raise ValueError(f"Неизвестный параметр «{name}».")
            if name in pending:
                raise ValueError(f"Циклическая зависимость параметра «{name}».")
            if name in completed:
                return parameters[name]
            pending.add(name)
            expression = normalized_expressions.get(f"{identifier}.{name}")
            value = Parser(expression, resolve).evaluate() if expression is not None else parameters[name]
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                raise ValueError(f"Параметр «{name}» должен быть конечным числом.")
            minimum = MINIMUMS[part["template"]][name]
            if value < minimum:
                raise ValueError(f"Параметр «{name}» должен быть не меньше {minimum:g} мм.")
            parameters[name] = float(value)
            pending.remove(name)
            completed.add(name)
            return parameters[name]

        for name in parameters:
            resolve(name)
    return {"parts": resolved, "expressions": normalized_expressions}
