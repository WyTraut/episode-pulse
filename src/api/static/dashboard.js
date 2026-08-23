const elements = {
  badge: document.querySelector("#live-badge"),
  liveLabel: document.querySelector("#live-label"),
  checkedAt: document.querySelector("#checked-at"),
  changedAt: document.querySelector("#changed-at"),
  showCount: document.querySelector("#show-count"),
  featuredShows: document.querySelector("#featured-shows"),
  loadStatus: document.querySelector("#load-status"),
  refreshButton: document.querySelector("#refresh-button"),
  rankingRows: document.querySelector("#ranking-rows"),
};

const numberFormatter = new Intl.NumberFormat();
const dateFormatter = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});
const featuredTones = ["tone-dark", "tone-blue", "tone-violet", "tone-warm", "tone-green"];

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
  signal.value = show.watcher_count;
  signal.setAttribute(
    "aria-label",
    `${show.title}: ${numberFormatter.format(show.watcher_count)} watchers`,
  );
  return signal;
}

function renderFeaturedShows(shows) {
  const visibleShows = shows.slice(0, 5);
  const maximumWatchers = Math.max(...visibleShows.map((show) => show.watcher_count), 1);
  const fragment = document.createDocumentFragment();

  visibleShows.forEach((show, index) => {
    const card = document.createElement("article");
    card.className = `featured-card ${featuredTones[index]}`;
    card.dataset.rank = String(show.rank).padStart(2, "0");

    const topline = document.createElement("div");
    topline.className = "featured-topline";
    const rank = document.createElement("p");
    rank.textContent = `Rank ${String(show.rank).padStart(2, "0")}`;
    const label = document.createElement("span");
    label.textContent = index === 0 ? "Leading now" : "Trending";
    topline.append(rank, label);

    const content = document.createElement("div");
    content.className = "featured-content";
    const title = document.createElement("h3");
    title.textContent = show.title;
    const count = document.createElement("p");
    count.className = "featured-count";
    const strongCount = document.createElement("strong");
    strongCount.textContent = numberFormatter.format(show.watcher_count);
    count.append(strongCount, " watchers");
    content.append(title, count, createSignal(show, maximumWatchers));

    card.append(topline, content);
    fragment.append(card);
  });

  elements.featuredShows.replaceChildren(fragment);
}

function renderRows(shows) {
  const visibleShows = shows.slice(0, 20);
  const maximumWatchers = Math.max(...visibleShows.map((show) => show.watcher_count), 1);
  const fragment = document.createDocumentFragment();

  visibleShows.forEach((show) => {
    const row = document.createElement("tr");

    const rankCell = document.createElement("td");
    rankCell.className = "rank-number";
    rankCell.textContent = String(show.rank);

    const titleCell = document.createElement("td");
    titleCell.className = "show-name";
    titleCell.textContent = show.title;

    const watcherCell = document.createElement("td");
    watcherCell.className = "number-column";
    watcherCell.textContent = numberFormatter.format(show.watcher_count);

    const signalCell = document.createElement("td");
    signalCell.className = "signal-column";
    signalCell.append(createSignal(show, maximumWatchers));

    row.append(rankCell, titleCell, watcherCell, signalCell);
    fragment.append(row);
  });

  elements.rankingRows.replaceChildren(fragment);
}

function renderSnapshot(data) {
  const shows = Array.isArray(data.shows) ? data.shows : [];

  if (shows.length === 0) {
    throw new Error("The latest snapshot contains no shows.");
  }

  elements.checkedAt.textContent = formatDate(data.checked_at);
  elements.changedAt.textContent = formatDate(data.changed_at);
  elements.showCount.textContent = numberFormatter.format(shows.length);
  renderFeaturedShows(shows);
  renderRows(shows);

  elements.badge.classList.remove("is-error", "is-stale");
  if (isStale(data.checked_at)) {
    elements.badge.classList.add("is-stale");
    elements.liveLabel.textContent = "Update delayed";
  } else {
    elements.liveLabel.textContent = "Live signal";
  }

  elements.loadStatus.textContent = `Showing the latest ${Math.min(shows.length, 20)} of ${shows.length} observed shows.`;
  elements.loadStatus.classList.remove("is-error");
}

async function loadTrending() {
  elements.refreshButton.disabled = true;
  elements.loadStatus.textContent = "Loading the latest snapshot…";
  elements.loadStatus.classList.remove("is-error");

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

elements.refreshButton.addEventListener("click", loadTrending);
loadTrending();
window.setInterval(loadTrending, 60 * 1000);
