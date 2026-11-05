import "./PaperPlaneMotion.css";

export function PaperPlaneMotion() {
  return (
    <div className="paper-plane-motion" aria-hidden="true">
      <svg viewBox="0 0 380 240" role="img">
        <defs>
          <linearGradient id="plane-wing" x1="76" y1="64" x2="282" y2="151" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="#ffffff" />
            <stop offset="1" stopColor="#dff4fa" />
          </linearGradient>
          <linearGradient id="plane-fold" x1="128" y1="130" x2="266" y2="130" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="#bfe9f3" />
            <stop offset="1" stopColor="#ffffff" />
          </linearGradient>
        </defs>

        <path className="plane-trail trail-one" d="M40 151C94 112 138 98 198 112" />
        <path className="plane-trail trail-two" d="M74 180C126 148 169 139 226 150" />
        <path className="plane-trail trail-three" d="M28 118C85 79 132 64 190 76" />

        <g className="plane-wrap">
          <path className="plane-shadow" d="M86 112l215-66-66 154-49-63-57 35 25-49z" />
          <path className="plane-body" d="M86 106l215-66-70 154-50-66z" />
          <path className="plane-wing-main" d="M86 106l215-66-120 88z" />
          <path className="plane-wing-fold" d="M181 128l50 66 70-154z" />
          <path className="plane-fold-line" d="M181 128l-52 39 25-49" />
        </g>

        <circle className="spark spark-one" cx="72" cy="87" r="3" />
        <circle className="spark spark-two" cx="112" cy="184" r="2.5" />
        <circle className="spark spark-three" cx="242" cy="67" r="2.5" />
      </svg>
    </div>
  );
}
