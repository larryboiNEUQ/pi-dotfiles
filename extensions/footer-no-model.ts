/**
 * Footer without model name — keeps stock token/cost/context stats,
 * drops the right-side model display so it does not duplicate pi-spark's editor border.
 *
 * Requires spark.json: { "footer": false } so pi-spark does not replace the footer first.
 */

import { isAbsolute, relative, resolve, sep } from "node:path";
import type { ExtensionAPI, ExtensionContext, ReadonlyFooterDataProvider, Theme } from "@earendil-works/pi-coding-agent";
import { truncateToWidth } from "@earendil-works/pi-tui";

function sanitizeStatusText(text: string): string {
	return text
		.replace(/[\r\n\t]/g, " ")
		.replace(/ +/g, " ")
		.trim();
}

function formatTokens(count: number): string {
	if (count < 1000) return count.toString();
	if (count < 10000) return `${(count / 1000).toFixed(1)}k`;
	if (count < 1000000) return `${Math.round(count / 1000)}k`;
	if (count < 10000000) return `${(count / 1000000).toFixed(1)}M`;
	return `${Math.round(count / 1000000)}M`;
}

function formatCwdForFooter(cwd: string, home: string | undefined): string {
	if (!home) return cwd;
	const resolvedCwd = resolve(cwd);
	const resolvedHome = resolve(home);
	const relativeToHome = relative(resolvedHome, resolvedCwd);
	const isInsideHome =
		relativeToHome === "" ||
		(relativeToHome !== ".." && !relativeToHome.startsWith(`..${sep}`) && !isAbsolute(relativeToHome));
	if (!isInsideHome) return cwd;
	return relativeToHome === "" ? "~" : `~${sep}${relativeToHome}`;
}

type UsageTotals = {
	input: number;
	output: number;
	cacheRead: number;
	cacheWrite: number;
	cost: number;
};

function createUsageTotals(): UsageTotals {
	return { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, cost: 0 };
}

function addUsageToTotals(
	totals: UsageTotals,
	usage: {
		input: number;
		output: number;
		cacheRead: number;
		cacheWrite: number;
		cost: { total: number };
	},
): void {
	totals.input += usage.input;
	totals.output += usage.output;
	totals.cacheRead += usage.cacheRead;
	totals.cacheWrite += usage.cacheWrite;
	totals.cost += usage.cost.total;
}

class FooterNoModel {
	constructor(
		private ctx: ExtensionContext,
		private theme: Theme,
		private footerData: ReadonlyFooterDataProvider,
	) {}

	invalidate(): void {}

	dispose(): void {}

	render(width: number): string[] {
		const usageTotals = createUsageTotals();
		let latestCacheHitRate: number | undefined;

		for (const entry of this.ctx.sessionManager.getEntries()) {
			if (entry.type === "message" && entry.message.role === "assistant") {
				const usage = entry.message.usage;
				if (!usage) continue;
				addUsageToTotals(usageTotals, usage);
				const latestPromptTokens = usage.input + usage.cacheRead + usage.cacheWrite;
				latestCacheHitRate =
					latestPromptTokens > 0 ? (usage.cacheRead / latestPromptTokens) * 100 : undefined;
			} else if (entry.type === "message" && entry.message.role === "toolResult" && entry.message.usage) {
				addUsageToTotals(usageTotals, entry.message.usage);
			} else if ((entry.type === "branch_summary" || entry.type === "compaction") && entry.usage) {
				addUsageToTotals(usageTotals, entry.usage);
			}
		}

		const contextUsage = this.ctx.getContextUsage();
		const contextWindow = contextUsage?.contextWindow ?? this.ctx.model?.contextWindow ?? 0;
		const contextPercentValue = contextUsage?.percent ?? 0;
		const contextPercent = contextUsage?.percent !== null && contextUsage?.percent !== undefined
			? contextPercentValue.toFixed(1)
			: "?";

		let pwd = formatCwdForFooter(
			this.ctx.sessionManager.getCwd(),
			process.env.HOME || process.env.USERPROFILE,
		);
		const branch = this.footerData.getGitBranch();
		if (branch) pwd = `${pwd} (${branch})`;
		const sessionName = this.ctx.sessionManager.getSessionName();
		if (sessionName) pwd = `${pwd} • ${sessionName}`;

		const statsParts: string[] = [];
		if (usageTotals.input) statsParts.push(`↑${formatTokens(usageTotals.input)}`);
		if (usageTotals.output) statsParts.push(`↓${formatTokens(usageTotals.output)}`);
		if (usageTotals.cacheRead) statsParts.push(`R${formatTokens(usageTotals.cacheRead)}`);
		if (usageTotals.cacheWrite) statsParts.push(`W${formatTokens(usageTotals.cacheWrite)}`);
		if ((usageTotals.cacheRead > 0 || usageTotals.cacheWrite > 0) && latestCacheHitRate !== undefined) {
			statsParts.push(`CH${latestCacheHitRate.toFixed(1)}%`);
		}

		const model = this.ctx.model;
		const usingSubscription = model
			? model.provider === "kimi-coding" || this.ctx.modelRegistry.isUsingOAuth(model)
			: false;
		if (usageTotals.cost || usingSubscription) {
			statsParts.push(`$${usageTotals.cost.toFixed(3)}${usingSubscription ? " (sub)" : ""}`);
		}

		// Match stock footer context style; always show (auto) — compaction is on by default.
		const autoIndicator = " (auto)";
		const contextPercentDisplay =
			contextPercent === "?"
				? `?/${formatTokens(contextWindow)}${autoIndicator}`
				: `${contextPercent}%/${formatTokens(contextWindow)}${autoIndicator}`;

		let contextPercentStr: string;
		if (contextPercentValue > 90) {
			contextPercentStr = this.theme.fg("error", contextPercentDisplay);
		} else if (contextPercentValue > 70) {
			contextPercentStr = this.theme.fg("warning", contextPercentDisplay);
		} else {
			contextPercentStr = contextPercentDisplay;
		}
		statsParts.push(contextPercentStr);

		// Intentionally no right-side model — pi-spark editor border already shows it.
		const statsLine = truncateToWidth(statsParts.join(" "), width, "...");
		const dimStats = this.theme.fg("dim", statsLine);
		const pwdLine = truncateToWidth(this.theme.fg("dim", pwd), width, this.theme.fg("dim", "..."));
		const lines = [pwdLine, dimStats];

		const extensionStatuses = this.footerData.getExtensionStatuses();
		if (extensionStatuses.size > 0) {
			const sortedStatuses = Array.from(extensionStatuses.entries())
				.sort(([a], [b]) => a.localeCompare(b))
				.map(([, text]) => sanitizeStatusText(text));
			const statusLine = sortedStatuses.join(" ");
			lines.push(truncateToWidth(statusLine, width, this.theme.fg("dim", "...")));
		}

		return lines;
	}
}

export default function (pi: ExtensionAPI) {
	pi.on("session_start", (_event, ctx) => {
		if (ctx.mode !== "tui") return;
		ctx.ui.setFooter((_tui, theme, footerData) => new FooterNoModel(ctx, theme, footerData));
	});
}
