import { Badge } from "@/components/ui/badge";
import { decisionLabel, relativeTime } from "@/lib/labels";
import type { Decision } from "@/lib/types";

/**
 * Блок «Почему так»: последнее решение автоматики человеческим языком (US3).
 *
 * @param props Решение автоматики.
 * @returns Причина решения либо честное «решений не было».
 */
export function DecisionPanel({ decision }: { decision?: Decision | null }) {
    if (!decision) {
        return (
            <p className="text-muted text-sm">
                Автоматика ещё не принимала решений по этому прибору.
            </p>
        );
    }

    return (
        <div data-testid="decision-panel" className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
                <Badge variant={decision.outcome === "denied" ? "warning" : "success"}>
                    {decisionLabel(decision.outcome)}
                </Badge>
                <span className="min-w-0 text-sm break-words">{decision.reason_text}</span>
            </div>
            <div className="text-muted text-xs">
                {relativeTime(decision.at)}
                {decision.trigger ? <span> · событие: {decision.trigger}</span> : null}
            </div>
        </div>
    );
}
