import type { CommandDef, HelpArticle, HelpIndex } from "./types";

const STOP_WORDS = new Set([
  "а", "без", "бы", "в", "во", "для", "до", "же", "и", "из", "или", "как",
  "ли", "мне", "на", "над", "о", "об", "от", "по", "под", "при", "про", "с",
  "со", "у", "что", "чтобы", "это", "я", "сделать", "можно", "нужно",
  "выполнить", "настроить", "найти", "показать", "помоги", "создать", "создавать",
]);

export interface HelpAnswerSource {
  article: HelpArticle;
  excerpt: string;
  commands: CommandDef[];
  score: number;
}

let cachedIndex: Promise<HelpIndex> | null = null;

function normalize(value: string): string {
  return value.normalize("NFKC").toLowerCase().replaceAll("ё", "е");
}

function tokens(value: string): string[] {
  return (normalize(value).match(/[\p{L}\p{N}]+/gu) ?? [])
    .filter((token) => token.length >= 2 && !STOP_WORDS.has(token));
}

function tokenSimilarity(queryToken: string, candidate: string): number {
  if (queryToken === candidate) return 1;
  if (Math.min(queryToken.length, candidate.length) >= 4 &&
      Math.min(queryToken.length, candidate.length) / Math.max(queryToken.length, candidate.length) >= 0.5 &&
      (queryToken.startsWith(candidate) || candidate.startsWith(queryToken))) {
    return 0.72;
  }
  return 0;
}

function fieldScore(queryTokens: string[], value: string, weight: number): number {
  const candidateTokens = tokens(value);
  return queryTokens.reduce((score, queryToken) => {
    const best = candidateTokens.reduce(
      (current, candidate) => Math.max(current, tokenSimilarity(queryToken, candidate)),
      0,
    );
    return score + best * weight;
  }, 0);
}

function articleScore(
  article: HelpArticle,
  queryTokens: string[],
  commandById: Map<string, CommandDef>,
): number {
  const commandText = article.commands
    .map((commandId) => {
      const command = commandById.get(commandId);
      return command ? `${command.command_id} ${command.title}` : "";
    })
    .join(" ");
  return fieldScore(queryTokens, article.title, 10) +
    fieldScore(queryTokens, article.synonyms.join(" "), 8) +
    fieldScore(queryTokens, article.help_id, 5) +
    fieldScore(queryTokens, commandText, 7) +
    fieldScore(queryTokens, article.body_markdown, 1);
}

function articleSections(markdown: string): string[] {
  const sections: string[] = [];
  let current: string[] = [];
  for (const line of markdown.split(/\r?\n/)) {
    if (/^##\s+/.test(line) && current.length > 0) {
      sections.push(current.join("\n").trim());
      current = [line];
    } else {
      current.push(line);
    }
  }
  if (current.length > 0) sections.push(current.join("\n").trim());
  return sections.filter((section) =>
    section.split(/\r?\n/).some((line) => line.trim() && !/^#{1,4}\s+/.test(line))
  );
}

function relevantExcerpt(article: HelpArticle, queryTokens: string[], query: string): string {
  const sections = articleSections(article.body_markdown);
  const proceduralIntent = /(как|сдела|созда|настро|выполн|пошаг)/u.test(normalize(query));
  const ranked = sections
    .map((section, index) => ({
      section,
      index,
      score: fieldScore(queryTokens, section.split("\n", 1)[0] ?? "", 5) +
        fieldScore(queryTokens, section, 1) +
        (proceduralIntent && /^##\s+(пошагово|как\b|где находится|что нужно)/iu.test(section)
          ? 12
          : 0),
    }))
    .sort((left, right) => right.score - left.score || left.index - right.index);
  const selected = ranked[0]?.section ?? article.body_markdown;
  if (selected.length <= 1200) return selected;
  const boundary = selected.lastIndexOf("\n", 1200);
  return `${selected.slice(0, boundary > 600 ? boundary : 1200).trim()}…`;
}

export function findHelpAnswers(
  index: HelpIndex,
  query: string,
  commands: CommandDef[],
  limit = 3,
): HelpAnswerSource[] {
  const queryTokens = tokens(query);
  if (queryTokens.length === 0 || limit <= 0) return [];
  const commandById = new Map(commands.map((command) => [command.command_id, command]));
  return index.articles
    .map((article) => ({
      article,
      score: articleScore(article, queryTokens, commandById),
    }))
    .filter((candidate) => candidate.score > 0)
    .sort((left, right) => right.score - left.score ||
      left.article.title.localeCompare(right.article.title, "ru"))
    .slice(0, limit)
    .map(({ article, score }) => ({
      article,
      score,
      excerpt: relevantExcerpt(article, queryTokens, query),
      commands: article.commands
        .map((commandId) => commandById.get(commandId))
        .filter((command): command is CommandDef => command != null),
    }));
}

export function loadHelpIndex(): Promise<HelpIndex> {
  if (!cachedIndex) {
    cachedIndex = fetch("/help/index.json")
      .then((response) => {
        if (!response.ok) throw new Error(`help_index_http_${response.status}`);
        return response.json();
      })
      .then((value: HelpIndex) => ({
        articles: Array.isArray(value?.articles) ? value.articles : [],
      }))
      .catch((error) => {
        cachedIndex = null;
        throw error;
      });
  }
  return cachedIndex;
}
