import type {
  GoldQueryItem,
  GoldRoute,
  GoldTagFilter,
  TableCategory,
  TableSummary,
} from "../types/phase1";

export function filterTables(
  tables: TableSummary[],
  category: TableCategory,
  search: string
): TableSummary[] {
  const q = search.trim().toLowerCase();
  return tables.filter((tbl) => {
    if (category !== "all" && tbl.category !== category) {
      return false;
    }
    if (!q) {
      return true;
    }
    return (
      tbl.table_name.toLowerCase().includes(q) ||
      tbl.purpose.toLowerCase().includes(q) ||
      tbl.columns.some((c) => c.name.toLowerCase().includes(q))
    );
  });
}

export function filterGoldQueries(
  queries: GoldQueryItem[],
  route: GoldRoute,
  tag: GoldTagFilter,
  search: string
): GoldQueryItem[] {
  const q = search.trim().toLowerCase();
  return queries.filter((item) => {
    if (route !== "all" && item.route !== route) {
      return false;
    }
    if (tag === "follow_up" && !item.is_follow_up) {
      return false;
    }
    if (tag === "adversarial" && !item.is_adversarial) {
      return false;
    }
    if (tag === "paraphrase" && !item.paraphrase_group) {
      return false;
    }
    if (!q) {
      return true;
    }
    return (
      item.query_id.toLowerCase().includes(q) ||
      item.query.toLowerCase().includes(q) ||
      item.expected_tables.some((t) => t.toLowerCase().includes(q)) ||
      item.expected_answer_facts.some((f) => f.toLowerCase().includes(q))
    );
  });
}

export function formatCategoryLabel(category: string): string {
  switch (category) {
    case "core":
      return "Core Table";
    case "distractor":
      return "Distractor";
    case "related":
      return "Academic Support";
    case "rag_infra":
      return "RAG Index";
    default:
      return category;
  }
}

export function formatRouteLabel(route: string): string {
  switch (route) {
    case "sql":
      return "SQL";
    case "vector":
      return "Vector";
    case "hybrid":
      return "Hybrid";
    case "out_of_scope":
      return "Out of Scope";
    default:
      return route;
  }
}

export function formatPlantedCaseLabel(code: string): string {
  return code
    .replace(/_/g, " ")
    .replace(/\b\w/g, (ch) => ch.toUpperCase());
}
