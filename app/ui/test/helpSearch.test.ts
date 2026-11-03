import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { findHelpAnswers } from "../src/helpSearch.ts";
import type { CommandDef, HelpIndex } from "../src/types.ts";

const root = new URL("../../..", import.meta.url);

async function shippedData(): Promise<{ index: HelpIndex; commands: CommandDef[] }> {
  const [indexRaw, commandsRaw] = await Promise.all([
    readFile(new URL("app/ui/public/help/index.json", root), "utf8"),
    readFile(new URL("app/shared/commands.json", root), "utf8"),
  ]);
  return {
    index: JSON.parse(indexRaw) as HelpIndex,
    commands: (JSON.parse(commandsRaw) as { commands: CommandDef[] }).commands,
  };
}

test("находит статью об изгибе фланца и только зарегистрированные команды", async () => {
  const { index, commands } = await shippedData();
  const answers = findHelpAnswers(index, "Как сделать перпендикулярный изгиб фланца?", commands);
  assert.equal(answers[0]?.article.help_id, "izgib-plastiny");
  assert.deepEqual(answers[0]?.commands.map((command) => command.command_id), ["op.sheet_bend"]);
  assert.match(answers[0]?.excerpt ?? "", /выберите внешнюю вертикальную грань/i);
});

test("понимает словоформу запроса об экспорте", async () => {
  const { index, commands } = await shippedData();
  const answers = findHelpAnswers(index, "Как экспортировать STL для печати?", commands);
  assert.match(answers[0]?.article.help_id ?? "", /^eksport-/);
});

test("не возвращает незарегистрированную команду из повреждённой статьи", () => {
  const index: HelpIndex = {
    articles: [{
      help_id: "safe",
      title: "Безопасная статья",
      synonyms: ["проверка"],
      commands: ["known.command", "invented.command"],
      related: [],
      body_markdown: "# Безопасная статья\n\nТочный текст ответа.",
    }],
  };
  const commands = [{
    command_id: "known.command",
    title: "Известная команда",
    help_id: "safe",
    shortcut: null,
    availability: "always" as const,
    params: [],
  }];
  const answers = findHelpAnswers(index, "проверка", commands);
  assert.deepEqual(answers[0]?.commands.map((command) => command.command_id), ["known.command"]);
  assert.equal(answers[0]?.excerpt.includes("Точный текст ответа."), true);
});

test("не делает вид, что нашёл ответ для пустого или общего запроса", async () => {
  const { index, commands } = await shippedData();
  assert.deepEqual(findHelpAnswers(index, "как это сделать", commands), []);
  assert.deepEqual(findHelpAnswers(index, "Как создать квантовый телепортатор?", commands), []);
  assert.deepEqual(findHelpAnswers(index, "   ", commands), []);
});
