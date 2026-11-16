import { useEffect, useMemo } from "react";
import L from "leaflet";
import { GeoJSON, MapContainer, TileLayer, useMap } from "react-leaflet";
import "leaflet.markercluster";
import "leaflet.heat";
import type { FeatureCollection, Geometry } from "geojson";
import { categoryMeta, statusMeta } from "../lib/meta";
import { formatDateTime } from "../lib/format";
import type { ForecastMap, MapComplaint, Ward } from "../lib/types";

const CENTER: [number, number] = [12.9716, 77.5946];

// OpenStreetMap's public raster tiles need no API key.  CARTO's keyless
// basemaps started returning "API KEY REQUIRED" tiles, which broke the map, so
// the dark theme is produced with a CSS filter over the same OSM tiles (see
// `.map-tiles-dark` in styles/index.css) instead of a paid tile provider.
const TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => {
    const map: Record<string, string> = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    };
    return map[character] ?? character;
  });
}

function clusterIcon(cluster: { getChildCount(): number }) {
  const count = cluster.getChildCount();
  const size = count < 10 ? 30 : count < 50 ? 34 : count < 200 ? 39 : 44;
  return L.divIcon({
    html: `<span>${count}</span>`,
    className: "civic-cluster",
    iconSize: [size, size],
  });
}

function ClusterMarkers({ points, theme }: { points: MapComplaint[]; theme: string }) {
  const map = useMap();

  useEffect(() => {
    if (!points.length) return;
    const group = L.markerClusterGroup({
      showCoverageOnHover: false,
      maxClusterRadius: 48,
      disableClusteringAtZoom: 16,
      iconCreateFunction: clusterIcon,
    });

    for (const point of points) {
      const [lng, lat] = point.location.coordinates;
      const meta = categoryMeta[point.category];
      const status = statusMeta[point.status];
      const marker = L.circleMarker([lat, lng], {
        radius: 5.5,
        weight: 1.5,
        color: theme === "dark" ? "#131c20" : "#ffffff",
        fillColor:
          point.status === "resolved" || point.status === "closed"
            ? theme === "dark"
              ? "#67bd90"
              : "#1f7a4d"
            : theme === "dark"
              ? "#78b4cb"
              : "#1b526d",
        fillOpacity: 0.92,
      });
      marker.bindPopup(
        `<div class="civic-popup">
          <p class="civic-popup-kicker">${escapeHtml(meta.label)} · Ward ${point.ward ?? "—"}</p>
          <p class="civic-popup-title">${escapeHtml(point.title)}</p>
          <div class="civic-popup-meta">
            <span>${escapeHtml(status.label)}</span>
            <span>Priority ${point.priority === null ? "—" : Math.round(point.priority)}</span>
          </div>
          <p class="civic-popup-time">Reported ${escapeHtml(formatDateTime(point.created_at))}</p>
          <a class="civic-popup-link" href="/queue/${point.id}" target="_blank" rel="noreferrer">Open case</a>
        </div>`,
        { closeButton: false, minWidth: 210, maxWidth: 260 },
      );
      group.addLayer(marker);
    }

    map.addLayer(group);
    return () => {
      map.removeLayer(group);
    };
  }, [map, points, theme]);

  return null;
}

function HeatLayer({ points }: { points: MapComplaint[] }) {
  const map = useMap();

  useEffect(() => {
    if (!points.length) return;
    const layer = L.heatLayer(
      points.map((point) => [point.location.coordinates[1], point.location.coordinates[0], 0.55]),
      {
        radius: 26,
        blur: 22,
        maxZoom: 16,
        minOpacity: 0.16,
        gradient: { 0.2: "#9fd0d8", 0.45: "#5a93a8", 0.7: "#1b526d", 0.9: "#a33a32" },
      },
    );
    layer.addTo(map);
    return () => {
      map.removeLayer(layer);
    };
  }, [map, points]);

  return null;
}

export function CivicMap({
  complaints,
  wards,
  heat,
  forecast,
  showForecast,
  showWards,
  theme,
  center = CENTER,
  zoom = 11,
}: {
  complaints: MapComplaint[];
  wards: Ward[];
  heat: boolean;
  forecast: ForecastMap | null;
  showForecast: boolean;
  showWards: boolean;
  theme: "light" | "dark";
  center?: [number, number];
  zoom?: number;
}) {
  const forecastByWard = useMemo(() => {
    const map = new Map<number, number>();
    for (const item of forecast?.items ?? []) map.set(item.ward, item.total_predicted);
    return map;
  }, [forecast]);

  const maxForecast = useMemo(
    () => Math.max(1, ...[...forecastByWard.values()]),
    [forecastByWard],
  );

  const collection = useMemo<FeatureCollection<Geometry>>(
    () => ({
      type: "FeatureCollection",
      features: wards.map((ward) => ({
        type: "Feature",
        id: ward.ward_no,
        properties: {
          ward_no: ward.ward_no,
          name: ward.name,
          open: ward.complaint_count,
          predicted: forecastByWard.get(ward.ward_no) ?? 0,
        },
        geometry: ward.geometry,
      })),
    }),
    [wards, forecastByWard],
  );

  const accent = theme === "dark" ? "#78b4cb" : "#1b526d";

  return (
    <MapContainer
      center={center}
      zoom={zoom}
      minZoom={9}
      maxZoom={18}
      scrollWheelZoom
      className="h-full w-full"
      aria-label="Complaint map of Bengaluru"
    >
      <TileLayer
        className={theme === "dark" ? "map-tiles map-tiles-dark" : "map-tiles"}
        url={TILES}
        attribution={ATTRIBUTION}
        maxZoom={19}
      />

      {showWards ? (
        <GeoJSON
          key={`wards-${showForecast ? "forecast" : "plain"}-${theme}`}
          data={collection}
          style={(feature) => {
            const predicted = Number(feature?.properties?.predicted ?? 0);
            const ratio = Math.min(1, predicted / maxForecast);
            return {
              color: accent,
              weight: showForecast ? 1.2 : 0.9,
              opacity: showForecast ? 0.85 : 0.5,
              fillColor: accent,
              fillOpacity: showForecast ? 0.08 + ratio * 0.42 : 0.03,
              dashArray: showForecast ? undefined : "3 3",
            };
          }}
          onEachFeature={(feature, layer) => {
            const properties = feature.properties as {
              name: string;
              ward_no: number;
              open: number;
              predicted: number;
            };
            const forecastLine = showForecast
              ? `<br/>Predicted 14-day volume: <strong>${properties.predicted}</strong>`
              : "";
            layer.bindTooltip(
              `<strong>Ward ${properties.ward_no} · ${escapeHtml(properties.name)}</strong><br/>Open now: ${properties.open}${forecastLine}`,
              { className: "ward-tooltip", sticky: true },
            );
          }}
        />
      ) : null}

      {heat ? <HeatLayer points={complaints} /> : null}
      <ClusterMarkers points={complaints} theme={theme} />
    </MapContainer>
  );
}
