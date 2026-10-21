// Безопасный парсер выражений: числа, + - * / ( ), имена параметров. Без eval.

type Token =
  | { t: "num"; v: number }
  | { t: "name"; v: string }
  | { t: "op"; v: string };

function tokenize(src: string): Token[] {
  const tokens: Token[] = [];
  let i = 0;
  const s = src.replace(/,/g, ".");
  while (i < s.length) {
    const c = s[i];
    if (/\s/.test(c)) { i++; continue; }
    if (/[0-9.]/.test(c)) {
      let j = i;
      while (j < s.length && /[0-9.]/.test(s[j])) j++;
      const raw = s.slice(i, j);
      const v = Number(raw);
      if (!Number.isFinite(v)) throw new Error(`Некорректное число «${raw}»`);
      tokens.push({ t: "num", v });
      i = j; continue;
    }
    if (/[a-zA-Z_а-яА-ЯёЁ]/.test(c)) {
      let j = i;
      while (j < s.length && /[\wа-яА-ЯёЁ]/.test(s[j])) j++;
      tokens.push({ t: "name", v: s.slice(i, j) });
      i = j; continue;
    }
    if ("+-*/()".includes(c)) {
      tokens.push({ t: "op", v: c });
      i++; continue;
    }
    throw new Error(`Недопустимый символ «${c}»`);
  }
  return tokens;
}

export function evalExpression(src: string, vars: Record<string, number>): number {
  const tokens = tokenize(src);
  let pos = 0;

  function peek(): Token | undefined { return tokens[pos]; }
  function eatOp(op: string): boolean {
    const t = peek();
    if (t && t.t === "op" && t.v === op) { pos++; return true; }
    return false;
  }

  function parseExpr(): number {
    let v = parseTerm();
    for (;;) {
      if (eatOp("+")) v += parseTerm();
      else if (eatOp("-")) v -= parseTerm();
      else return v;
    }
  }
  function parseTerm(): number {
    let v = parseFactor();
    for (;;) {
      if (eatOp("*")) v *= parseFactor();
      else if (eatOp("/")) {
        const d = parseFactor();
        if (d === 0) throw new Error("Деление на ноль");
        v /= d;
      } else return v;
    }
  }
  function parseFactor(): number {
    if (eatOp("-")) return -parseFactor();
    if (eatOp("+")) return parseFactor();
    const t = peek();
    if (!t) throw new Error("Выражение обрывается");
    if (t.t === "num") { pos++; return t.v; }
    if (t.t === "name") {
      pos++;
      if (!(t.v in vars)) throw new Error(`Неизвестный параметр «${t.v}»`);
      return vars[t.v];
    }
    if (t.t === "op" && t.v === "(") {
      pos++;
      const v = parseExpr();
      if (!eatOp(")")) throw new Error("Нет закрывающей скобки");
      return v;
    }
    throw new Error(`Неожиданный символ «${t.v}»`);
  }

  const result = parseExpr();
  if (pos < tokens.length) throw new Error("Лишние символы в конце выражения");
  if (!Number.isFinite(result)) throw new Error("Результат не является конечным числом");
  return result;
}
