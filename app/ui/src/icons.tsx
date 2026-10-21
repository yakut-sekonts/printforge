import React from "react";

const S: React.SVGProps<SVGSVGElement> = {
  width: 16, height: 16, viewBox: "0 0 16 16", fill: "none",
  stroke: "currentColor", strokeWidth: 1.5, strokeLinecap: "round", strokeLinejoin: "round",
  "aria-hidden": true,
};

export const IconPlate = () => (
  <svg {...S}><rect x="1.5" y="3.5" width="13" height="9" rx="1.5"/><circle cx="5" cy="8" r="1.4"/><circle cx="11" cy="8" r="1.4"/></svg>
);
export const IconUndo = () => (
  <svg {...S}><path d="M3 6.5h6a3.5 3.5 0 0 1 0 7H6"/><path d="M5.5 3.5 3 6.5l2.5 3"/></svg>
);
export const IconRedo = () => (
  <svg {...S}><path d="M13 6.5H7a3.5 3.5 0 0 0 0 7h3"/><path d="M10.5 3.5 13 6.5l-2.5 3"/></svg>
);
export const IconSave = () => (
  <svg {...S}><path d="M3 3h8l2 2v8H3z"/><path d="M5.5 3v3.5h5V3"/><path d="M5.5 13v-4h5v4"/></svg>
);
export const IconOpen = () => (
  <svg {...S}><path d="M2 5.5V13h12V6.5H8L6.5 4.5H3"/><path d="M2 5.5V4a1 1 0 0 1 1-1h3.5"/></svg>
);
export const IconExport = () => (
  <svg {...S}><path d="M8 2.5v8"/><path d="M4.8 7.3 8 10.5l3.2-3.2"/><path d="M3 13.5h10"/></svg>
);
export const IconQuestion = () => (
  <svg {...S}><circle cx="8" cy="8" r="6"/><path d="M6.2 6.2a1.9 1.9 0 1 1 2.6 1.8c-.5.2-.8.6-.8 1.2"/><circle cx="8" cy="11.3" r=".4" fill="currentColor"/></svg>
);
export const IconCursorQuestion = () => (
  <svg {...S}><path d="M4 2.5 12 9l-3.4.4L7 12.5z"/><path d="M11.5 12.2c.4-.7 1.6-.7 1.9 0 .2.5-.1 1-.6 1.2"/></svg>
);
export const IconCube = () => (
  <svg {...S}><path d="M8 1.8 14 4.8v6.4L8 14.2 2 11.2V4.8z"/><path d="M2 4.8l6 3 6-3"/><path d="M8 7.8v6.4"/></svg>
);
export const IconFit = () => (
  <svg {...S}><path d="M2.5 5.5v-3h3M10.5 2.5h3v3M13.5 10.5v3h-3M5.5 13.5h-3v-3"/><rect x="6" y="6" width="4" height="4" rx=".8"/></svg>
);
export const IconBack = () => (
  <svg {...S}><path d="M9.5 3 5 8l4.5 5"/></svg>
);
export const IconClose = () => (
  <svg {...S}><path d="M4 4l8 8M12 4l-8 8"/></svg>
);
export const IconCheck = () => (
  <svg {...S}><path d="M3 8.5 6.5 12 13 4.5"/></svg>
);
export const IconSearch = () => (
  <svg {...S}><circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5 14 14"/></svg>
);
export const IconBook = () => (
  <svg {...S}><path d="M3 3.5A1.5 1.5 0 0 1 4.5 2H13v11.5H4.5A1.5 1.5 0 0 0 3 15z"/><path d="M3 13.5V3.5"/></svg>
);
