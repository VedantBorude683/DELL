import type { ActiveSection } from "../types/phase1";

interface TopBarProps {
  activeSection: ActiveSection;
  onSelectSection: (section: ActiveSection) => void;
  onRunVerify: () => void;
  isVerifying: boolean;
}

const NAV_ITEMS: { id: ActiveSection; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "tables", label: "SQL & Schema" },
  { id: "handbooks", label: "Handbooks" },
  { id: "ingestion", label: "Ingestion" },
  { id: "gold", label: "Gold Set" },
];

export function TopBar({
  activeSection,
  onSelectSection,
  onRunVerify,
  isVerifying,
}: TopBarProps) {
  return (
    <header className="sticky top-0 z-30 border-b border-black/[0.06] bg-white/85 backdrop-blur-xl">
      <div className="mx-auto flex max-w-[1200px] items-center justify-between gap-8 px-6 py-4 lg:px-10">
        <button
          type="button"
          onClick={() => onSelectSection("overview")}
          className="text-left text-[17px] font-semibold tracking-[-0.02em] text-[#1D1D1F] whitespace-nowrap shrink-0 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[#0071E3]"
        >
          Alderwood Hybrid RAG
        </button>

        <nav
          aria-label="Primary navigation"
          className="hidden items-center gap-7 md:flex"
        >
          {NAV_ITEMS.map((item) => {
            const isActive = activeSection === item.id;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => onSelectSection(item.id)}
                className={`relative py-1 text-[14px] font-medium transition-colors duration-150 whitespace-nowrap shrink-0 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[#0071E3] ${
                  isActive
                    ? "text-[#1D1D1F]"
                    : "text-[#6E6E73] hover:text-[#1D1D1F]"
                }`}
              >
                {item.label}
                {isActive && (
                  <span
                    aria-hidden="true"
                    className="absolute inset-x-0 -bottom-[17px] h-[1.5px] bg-[#1D1D1F]"
                  />
                )}
              </button>
            );
          })}
        </nav>

        <div className="flex items-center shrink-0">
          <button
            type="button"
            onClick={onRunVerify}
            disabled={isVerifying}
            className="rounded-full bg-[#0071E3] px-5 py-2 text-[13px] font-medium text-white transition-colors duration-150 hover:bg-[#0077ED] disabled:opacity-60 whitespace-nowrap shrink-0 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#0071E3]"
          >
            {isVerifying ? "Running Tests..." : "Run All Tests"}
          </button>
        </div>
      </div>

      {/* Mobile section selector */}
      <div className="flex items-center gap-5 overflow-x-auto border-t border-black/[0.04] px-6 py-2.5 md:hidden">
        {NAV_ITEMS.map((item) => {
          const isActive = activeSection === item.id;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => onSelectSection(item.id)}
              className={`text-[13px] font-medium whitespace-nowrap shrink-0 ${
                isActive ? "text-[#0071E3]" : "text-[#6E6E73]"
              }`}
            >
              {item.label}
            </button>
          );
        })}
      </div>
    </header>
  );
}
