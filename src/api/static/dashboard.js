const elements = {
  badge: document.querySelector("#live-badge"),
  liveLabel: document.querySelector("#live-label"),
  checkedAt: document.querySelector("#checked-at"),
  changedAt: document.querySelector("#changed-at"),
  showCount: document.querySelector("#show-count"),
  featuredShows: document.querySelector("#featured-shows"),
  featuredPrevious: document.querySelector("#featured-previous"),
  featuredNext: document.querySelector("#featured-next"),
  loadStatus: document.querySelector("#load-status"),
  refreshButton: document.querySelector("#refresh-button"),
  rankingRows: document.querySelector("#ranking-rows"),
  drawer: document.querySelector("#show-detail"),
  drawerClose: document.querySelector("#drawer-close"),
  drawerTitle: document.querySelector("#drawer-title"),
  drawerStatus: document.querySelector("#drawer-status"),
  drawerContent: document.querySelector("#drawer-content"),
  drawerRank: document.querySelector("#drawer-rank"),
  drawerRankChange: document.querySelector("#drawer-rank-change"),
  drawerWatchers: document.querySelector("#drawer-watchers"),
  drawerWatcherChange: document.querySelector("#drawer-watcher-change"),
  sourceState: document.querySelector("#source-state"),
  sourceStateText: document.querySelector("#source-state-text"),
  chartTitle: document.querySelector("#chart-title"),
  chart: document.querySelector("#history-chart"),
  chartTooltip: document.querySelector("#chart-tooltip"),
  chartRange: document.querySelector("#chart-range"),
  chartToggles: document.querySelectorAll("[data-chart-metric]"),
};

const numberFormatter = new Intl.NumberFormat();
const signedNumberFormatter = new Intl.NumberFormat(undefined, { signDisplay: "always" });
const dateFormatter = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});
const timeFormatter = new Intl.DateTimeFormat(undefined, {
  hour: "numeric",
  minute: "2-digit",
});
const featuredTones = ["tone-dark", "tone-blue", "tone-violet", "tone-warm", "tone-green"];
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

let lastCollectionId = null;
let selectedShowId = null;
let selectedHistory = null;
let selectedMetric = "watcher_count";
let chartPoints = [];
let resizeFrame = null;

function formatDate(value) {
  if (!value) {
    return "Not provided";
  }

  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "Not provided" : dateFormatter.format(date);
}

function isStale(value) {
  const checkedAt = new Date(value).valueOf();
  return Number.isNaN(checkedAt) || Date.now() - checkedAt > 10 * 60 * 1000;
}

function createSignal(show, maximumWatchers) {
  const signal = document.createElement("progress");
  signal.max = maximumWatchers;
  signal.value = reducedMotion.matches ? show.watcher_count : 0;
  signal.setAttribute(
    "aria-label",
    `${show.title}: ${numberFormatter.format(show.watcher_count)} watchers`,
  );

  if (!reducedMotion.matches) {
    window.requestAnimationFrame(() => {
      const startedAt = performance.now();
      const animate = (now) => {
        const progress = Math.min((now - startedAt) / 600, 1);
        signal.value = show.watcher_count * (1 - Math.pow(1 - progress, 3));
        if (progress < 1) {
          window.requestAnimationFrame(animate);
        }
      };
      window.requestAnimationFrame(animate);
    });
  }

  return signal;
}

function movementDetails(show) {
  if (show.is_new) {
    return { label: "New", className: "movement-new" };
  }
  if (show.rank_change > 0) {
    return { label: `↑ ${show.rank_change}`, className: "movement-up" };
  }
  if (show.rank_change < 0) {
    return { label: `↓ ${Math.abs(show.rank_change)}`, className: "movement-down" };
  }
  if (show.rank_change === 0) {
    return { label: "Steady", className: "movement-steady" };
  }
  return { label: "Baseline", className: "movement-steady" };
}

function createMovementBadge(show) {
  const movement = movementDetails(show);
  const badge = document.createElement("span");
  badge.className = `movement-badge ${movement.className}`;
  badge.textContent = movement.label;
  return badge;
}

function watcherChangeLabel(value) {
  if (value === null || value === undefined) {
    return "Awaiting comparison";
  }
  if (value === 0) {
    return "No watcher change";
  }
  return `${signedNumberFormatter.format(value)} watchers`;
}

function renderFeaturedShows(shows, animateUpdate) {
  const visibleShows = shows.slice(0, 5);
  const maximumWatchers = Math.max(...visibleShows.map((show) => show.watcher_count), 1);
  const fragment = document.createDocumentFragment();

  visibleShows.forEach((show, index) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = `featured-card ${featuredTones[index]}`;
    if (animateUpdate) {
      card.classList.add("is-entering");
    }
    card.dataset.rank = String(show.rank).padStart(2, "0");
    card.dataset.showId = String(show.trakt_show_id);
    card.setAttribute("aria-label", `Open six-hour history for ${show.title}`);

    const topline = document.createElement("span");
    topline.className = "featured-topline";
    const rank = document.createElement("span");
    rank.textContent = `Rank ${String(show.rank).padStart(2, "0")}`;
    topline.append(rank, createMovementBadge(show));

    const content = document.createElement("span");
    content.className = "featured-content";
    const title = document.createElement("span");
    title.className = "featured-title";
    title.textContent = show.title;
    const count = document.createElement("span");
    count.className = "featured-count";
    const strongCount = document.createElement("strong");
    strongCount.textContent = numberFormatter.format(show.watcher_count);
    const change = document.createElement("span");
    change.className = "watcher-change";
    change.textContent = watcherChangeLabel(show.watcher_change);
    count.append(strongCount, " watchers", change);
    content.append(title, count, createSignal(show, maximumWatchers));

    card.append(topline, content);
    card.addEventListener("click", () => openShowHistory(show.trakt_show_id, show.title));
    fragment.append(card);
  });

  elements.featuredShows.replaceChildren(fragment);
  updateRailControls();
}

function renderRows(shows, animateUpdate) {
  const visibleShows = shows.slice(0, 20);
  const maximumWatchers = Math.max(...visibleShows.map((show) => show.watcher_count), 1);
  const fragment = document.createDocumentFragment();

  visibleShows.forEach((show) => {
    const row = document.createElement("tr");
    if (animateUpdate && (show.rank_change || show.watcher_change || show.is_new)) {
      row.classList.add("is-updated");
    }

    const rankCell = document.createElement("td");
    rankCell.className = "rank-number";
    rankCell.textContent = String(show.rank);

    const titleCell = document.createElement("td");
    const showButton = document.createElement("button");
    showButton.type = "button";
    showButton.className = "show-link";
    showButton.textContent = show.title;
    showButton.setAttribute("aria-label", `Open six-hour history for ${show.title}`);
    showButton.addEventListener("click", () => openShowHistory(show.trakt_show_id, show.title));
    titleCell.append(showButton);

    const watcherCell = document.createElement("td");
    watcherCell.className = "number-column";
    watcherCell.textContent = numberFormatter.format(show.watcher_count);

    const movementCell = document.createElement("td");
    movementCell.className = "movement-column";
    movementCell.append(createMovementBadge(show));
    const watcherDelta = document.createElement("span");
    watcherDelta.className = "table-watcher-change";
    watcherDelta.textContent = watcherChangeLabel(show.watcher_change);
    movementCell.append(watcherDelta);

    const signalCell = document.createElement("td");
    signalCell.className = "signal-column";
    signalCell.append(createSignal(show, maximumWatchers));

    row.append(rankCell, titleCell, watcherCell, movementCell, signalCell);
    fragment.append(row);
  });

  elements.rankingRows.replaceChildren(fragment);
}

function renderSnapshot(data) {
  const shows = Array.isArray(data.shows) ? data.shows : [];

  if (shows.length === 0) {
    throw new Error("The latest snapshot contains no shows.");
  }

  const isNewCollection = lastCollectionId !== data.collection_id;
  elements.checkedAt.textContent = formatDate(data.checked_at);
  elements.changedAt.textContent = formatDate(data.changed_at);
  elements.showCount.textContent = numberFormatter.format(shows.length);

  if (isNewCollection) {
    renderFeaturedShows(shows, lastCollectionId !== null);
    renderRows(shows, lastCollectionId !== null);
    lastCollectionId = data.collection_id;
  }

  elements.badge.classList.remove("is-error", "is-stale");
  if (isStale(data.checked_at)) {
    elements.badge.classList.add("is-stale");
    elements.liveLabel.textContent = "Update delayed";
  } else {
    elements.liveLabel.textContent = "Live signal";
  }

  const sourceStable = shows.every(
    (show) => show.rank_change === 0 && show.watcher_change === 0 && !show.is_new,
  );
  elements.loadStatus.textContent = sourceStable
    ? `Checked ${formatDate(data.checked_at)} · Trakt source stable since ${formatDate(data.changed_at)}.`
    : `Updated ${formatDate(data.checked_at)} · Showing the top ${Math.min(shows.length, 20)} of ${shows.length}.`;
  elements.loadStatus.classList.remove("is-error");

  if (isNewCollection && selectedShowId !== null && elements.drawer.open) {
    loadShowHistory(selectedShowId);
  }
}

async function loadTrending() {
  elements.refreshButton.disabled = true;
  elements.loadStatus.classList.remove("is-error");
  if (lastCollectionId === null) {
    elements.loadStatus.textContent = "Loading the latest snapshot…";
  }

  try {
    const response = await fetch("/api/trending", {
      headers: { Accept: "application/json" },
    });

    if (!response.ok) {
      throw new Error(`Request failed with status ${response.status}.`);
    }

    renderSnapshot(await response.json());
  } catch (error) {
    console.error(error);
    elements.badge.classList.add("is-error");
    elements.liveLabel.textContent = "Signal unavailable";
    elements.loadStatus.textContent = "The latest snapshot could not be loaded. Try again shortly.";
    elements.loadStatus.classList.add("is-error");
  } finally {
    elements.refreshButton.disabled = false;
  }
}

function updateRailControls() {
  const rail = elements.featuredShows;
  const maximumScroll = Math.max(rail.scrollWidth - rail.clientWidth, 0);
  elements.featuredPrevious.disabled = rail.scrollLeft <= 2;
  elements.featuredNext.disabled = rail.scrollLeft >= maximumScroll - 2;
}

function scrollFeatured(direction) {
  elements.featuredShows.scrollBy({
    left: direction * elements.featuredShows.clientWidth * 0.82,
    behavior: reducedMotion.matches ? "auto" : "smooth",
  });
}

function formatDelta(value, label) {
  if (value === null || value === undefined) {
    return "Awaiting baseline";
  }
  if (value === 0) {
    return `No ${label} change`;
  }
  return `${signedNumberFormatter.format(value)} ${label}`;
}

async function openShowHistory(showId, title) {
  selectedShowId = Number(showId);
  elements.drawerTitle.textContent = title;
  elements.drawerStatus.textContent = "Loading recent history…";
  elements.drawerStatus.classList.remove("is-error");
  elements.drawerContent.hidden = true;
  if (!elements.drawer.open) {
    elements.drawer.showModal();
  }
  await loadShowHistory(selectedShowId);
}

async function loadShowHistory(showId) {
  try {
    const response = await fetch(`/api/shows/${showId}/history`, {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      throw new Error(`Request failed with status ${response.status}.`);
    }
    selectedHistory = await response.json();
    renderShowHistory(selectedHistory);
  } catch (error) {
    console.error(error);
    elements.drawerStatus.textContent = "Recent history is still being prepared. Try again shortly.";
    elements.drawerStatus.classList.add("is-error");
    elements.drawerContent.hidden = true;
  }
}

function renderShowHistory(document) {
  const show = document.show;
  const points = document.points || [];
  elements.drawerTitle.textContent = show.title;
  elements.drawerRank.textContent = `#${show.current_rank}`;
  elements.drawerRankChange.textContent = formatDelta(show.rank_change, "ranks");
  elements.drawerWatchers.textContent = numberFormatter.format(show.current_watcher_count);
  elements.drawerWatcherChange.textContent = formatDelta(show.watcher_change, "watchers");

  const latestPoint = points[points.length - 1];
  const sourceStable = latestPoint && latestPoint.source_changed === false;
  elements.sourceState.classList.toggle("is-stable", sourceStable);
  elements.sourceStateText.textContent = sourceStable
    ? "Trakt returned the same source payload at the latest check. The flat line is real."
    : "The Trakt source changed at the latest check.";

  elements.drawerStatus.textContent = `${points.length} observations loaded.`;
  elements.drawerStatus.classList.remove("is-error");
  elements.drawerContent.hidden = false;
  elements.chartRange.textContent = points.length
    ? `${formatDate(points[0].checked_at)} – ${formatDate(points[points.length - 1].checked_at)}`
    : "No recent points available.";
  drawHistoryChart(true);
}

function chartValue(point) {
  return point[selectedMetric];
}

function drawHistoryChart(animate = false) {
  if (!selectedHistory || elements.drawerContent.hidden) {
    return;
  }

  const canvas = elements.chart;
  const context = canvas.getContext("2d");
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(Math.floor(rect.width * ratio), 1);
  canvas.height = Math.max(Math.floor(rect.height * ratio), 1);
  context.scale(ratio, ratio);

  const width = rect.width;
  const height = rect.height;
  const padding = { top: 24, right: 18, bottom: 34, left: 48 };
  const plotWidth = Math.max(width - padding.left - padding.right, 1);
  const plotHeight = Math.max(height - padding.top - padding.bottom, 1);
  const points = selectedHistory.points || [];
  const values = points.map(chartValue).filter((value) => value !== null && value !== undefined);
  chartPoints = [];

  context.clearRect(0, 0, width, height);
  if (values.length === 0) {
    context.fillStyle = "#6e6e73";
    context.font = "14px -apple-system, sans-serif";
    context.fillText("No observations for this metric yet.", padding.left, height / 2);
    return;
  }

  let minimum = Math.min(...values);
  let maximum = Math.max(...values);
  if (minimum === maximum) {
    minimum -= selectedMetric === "rank" ? 1 : Math.max(minimum * 0.05, 1);
    maximum += selectedMetric === "rank" ? 1 : Math.max(maximum * 0.05, 1);
  }

  const xForIndex = (index) =>
    padding.left + (points.length === 1 ? plotWidth / 2 : (index / (points.length - 1)) * plotWidth);
  const yForValue = (value) => {
    const normalized = (value - minimum) / (maximum - minimum);
    return selectedMetric === "rank"
      ? padding.top + normalized * plotHeight
      : padding.top + (1 - normalized) * plotHeight;
  };

  points.forEach((point, index) => {
    const value = chartValue(point);
    chartPoints.push({
      x: xForIndex(index),
      y: value === null || value === undefined ? null : yForValue(value),
      point,
      value,
    });
  });

  const renderFrame = (reveal) => {
    context.clearRect(0, 0, width, height);
    context.strokeStyle = "#d2d2d7";
    context.lineWidth = 1;
    context.fillStyle = "#6e6e73";
    context.font = "11px -apple-system, sans-serif";

    for (let line = 0; line <= 3; line += 1) {
      const y = padding.top + (line / 3) * plotHeight;
      context.beginPath();
      context.moveTo(padding.left, y);
      context.lineTo(width - padding.right, y);
      context.stroke();
      const labelValue = selectedMetric === "rank"
        ? minimum + (line / 3) * (maximum - minimum)
        : maximum - (line / 3) * (maximum - minimum);
      context.fillText(numberFormatter.format(Math.round(labelValue)), 4, y + 4);
    }

    context.save();
    context.beginPath();
    context.rect(padding.left, padding.top - 4, plotWidth * reveal, plotHeight + 8);
    context.clip();
    context.strokeStyle = "#0066cc";
    context.lineWidth = 3;
    context.lineJoin = "round";
    context.lineCap = "round";
    let drawing = false;
    context.beginPath();
    chartPoints.forEach((entry) => {
      if (entry.y === null) {
        drawing = false;
        return;
      }
      if (!drawing) {
        context.moveTo(entry.x, entry.y);
        drawing = true;
      } else {
        context.lineTo(entry.x, entry.y);
      }
    });
    context.stroke();

    chartPoints.forEach((entry) => {
      if (entry.y === null) {
        return;
      }
      context.beginPath();
      context.fillStyle = entry.point.source_changed === false ? "#86868b" : "#0066cc";
      context.arc(entry.x, entry.y, 3.5, 0, Math.PI * 2);
      context.fill();
    });
    context.restore();

    if (points.length) {
      context.fillStyle = "#6e6e73";
      context.fillText(timeFormatter.format(new Date(points[0].checked_at)), padding.left, height - 8);
      const lastLabel = timeFormatter.format(new Date(points[points.length - 1].checked_at));
      const lastWidth = context.measureText(lastLabel).width;
      context.fillText(lastLabel, width - padding.right - lastWidth, height - 8);
    }
  };

  if (!animate || reducedMotion.matches) {
    renderFrame(1);
    return;
  }

  const startedAt = performance.now();
  const animateFrame = (now) => {
    const progress = Math.min((now - startedAt) / 700, 1);
    renderFrame(1 - Math.pow(1 - progress, 3));
    if (progress < 1) {
      window.requestAnimationFrame(animateFrame);
    }
  };
  window.requestAnimationFrame(animateFrame);
}

function updateChartTooltip(event) {
  if (!chartPoints.length) {
    return;
  }
  const rect = elements.chart.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const nearest = chartPoints.reduce((best, entry) =>
    Math.abs(entry.x - x) < Math.abs(best.x - x) ? entry : best,
  );
  const valueLabel = nearest.value === null || nearest.value === undefined
    ? "Not in the trending collection"
    : selectedMetric === "rank"
      ? `Rank #${nearest.value}`
      : `${numberFormatter.format(nearest.value)} watchers`;
  const sourceLabel = nearest.point.source_changed === false ? " · source stable" : "";
  elements.chartTooltip.textContent = `${formatDate(nearest.point.checked_at)} · ${valueLabel}${sourceLabel}`;
}

function selectChartMetric(metric) {
  selectedMetric = metric;
  elements.chartToggles.forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.chartMetric === metric));
  });
  elements.chartTitle.textContent = metric === "rank" ? "Rank movement" : "Watcher activity";
  elements.chart.setAttribute(
    "aria-label",
    metric === "rank" ? "Recent rank movement chart" : "Recent watcher activity chart",
  );
  elements.chartTooltip.textContent = "Move across the chart to inspect a point.";
  drawHistoryChart(true);
}

elements.refreshButton.addEventListener("click", loadTrending);
elements.featuredPrevious.addEventListener("click", () => scrollFeatured(-1));
elements.featuredNext.addEventListener("click", () => scrollFeatured(1));
elements.featuredShows.addEventListener("scroll", updateRailControls, { passive: true });
elements.drawerClose.addEventListener("click", () => elements.drawer.close());
elements.drawer.addEventListener("click", (event) => {
  if (event.target === elements.drawer) {
    elements.drawer.close();
  }
});
elements.chartToggles.forEach((button) => {
  button.addEventListener("click", () => selectChartMetric(button.dataset.chartMetric));
});
elements.chart.addEventListener("pointermove", updateChartTooltip);
elements.chart.addEventListener("pointerleave", () => {
  elements.chartTooltip.textContent = "Move across the chart to inspect a point.";
});
window.addEventListener("resize", () => {
  window.cancelAnimationFrame(resizeFrame);
  resizeFrame = window.requestAnimationFrame(() => {
    updateRailControls();
    drawHistoryChart(false);
  });
});

loadTrending();
window.setInterval(loadTrending, 60 * 1000);
