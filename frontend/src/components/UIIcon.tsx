import React from 'react';

export type IconName =
  | 'logo'
  | 'dashboard'
  | 'servers'
  | 'inbounds'
  | 'clients'
  | 'traffic'
  | 'monitoring'
  | 'backup'
  | 'subscriptions'
  | 'user'
  | 'bell'
  | 'menu'
  | 'sun'
  | 'moon'
  | 'refresh'
  | 'plus'
  | 'download'
  | 'upload'
  | 'trash'
  | 'edit'
  | 'copy'
  | 'search'
  | 'warning'
  | 'clock'
  | 'check'
  | 'x'
  | 'link'
  | 'folder'
  | 'spinner'
  | 'statusOn'
  | 'statusOff';

interface UIIconProps {
  name: IconName;
  size?: number;
  className?: string;
}

export const UIIcon: React.FC<UIIconProps> = ({ name, size = 18, className }) => {
  const props = {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.9,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    className,
    'aria-hidden': true,
  };

  switch (name) {
    case 'logo':
      return (
        <svg {...props}>
          <path d="M3 12h2m2-4v8m4-11v14m4-12v10m4-6v2" />
        </svg>
      );
    case 'dashboard':
      return (
        <svg {...props}>
          <rect x="3" y="3" width="8" height="8" rx="2" />
          <rect x="13" y="3" width="8" height="5" rx="2" />
          <rect x="13" y="10" width="8" height="11" rx="2" />
          <rect x="3" y="13" width="8" height="8" rx="2" />
        </svg>
      );
    case 'servers':
      return (
        <svg {...props}>
          <rect x="3" y="4" width="18" height="7" rx="2" />
          <rect x="3" y="13" width="18" height="7" rx="2" />
          <path d="M7 8h.01M7 17h.01M10 8h2M10 17h2" />
        </svg>
      );
    case 'inbounds':
      return (
        <svg {...props}>
          <path d="M8 5h4a4 4 0 0 1 0 8H8" />
          <path d="M16 11h-4a4 4 0 0 0 0 8h4" />
          <path d="M10 9l4 6" />
        </svg>
      );
    case 'clients':
      return (
        <svg {...props}>
          <path d="M16 19a4 4 0 0 0-8 0" />
          <circle cx="12" cy="10" r="3.5" />
          <path d="M21 19a3.5 3.5 0 0 0-3-3.4M3 19a3.5 3.5 0 0 1 3-3.4" />
        </svg>
      );
    case 'traffic':
      return (
        <svg {...props}>
          <path d="M3 17h18" />
          <path d="M7 15V9M12 15V6M17 15v-3" />
          <path d="M5 7l3-2 4 2 5-3 2 2" />
        </svg>
      );
    case 'monitoring':
      return (
        <svg {...props}>
          <path d="M3 12h3l2.2-5L12 18l2.5-7H21" />
        </svg>
      );
    case 'backup':
      return (
        <svg {...props}>
          <rect x="4" y="4" width="16" height="16" rx="3" />
          <path d="M8 9h8M8 13h8M8 17h5" />
        </svg>
      );
    case 'subscriptions':
      return (
        <svg {...props}>
          <rect x="3" y="5" width="18" height="14" rx="2" />
          <path d="M3 9h18M8 13h8M8 16h5" />
        </svg>
      );
    case 'user':
      return (
        <svg {...props}>
          <circle cx="12" cy="8" r="3.2" />
          <path d="M5 19a7 7 0 0 1 14 0" />
        </svg>
      );
    case 'bell':
      return (
        <svg {...props}>
          <path d="M15 18H9" />
          <path d="M18 16H6l1.3-2.1a7 7 0 0 0 1-3.6V9a3.7 3.7 0 0 1 7.4 0v1.3a7 7 0 0 0 1 3.6Z" />
        </svg>
      );
    case 'menu':
      return (
        <svg {...props}>
          <path d="M4 7h16M4 12h16M4 17h16" />
        </svg>
      );
    case 'sun':
      return (
        <svg {...props}>
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2.3M12 19.7V22M4.9 4.9l1.6 1.6M17.5 17.5l1.6 1.6M2 12h2.3M19.7 12H22M4.9 19.1l1.6-1.6M17.5 6.5l1.6-1.6" />
        </svg>
      );
    case 'moon':
      return (
        <svg {...props}>
          <path d="M19.5 14.5A8 8 0 1 1 9.5 4.5a7 7 0 0 0 10 10Z" />
        </svg>
      );
    case 'refresh':
      return (
        <svg {...props}>
          <path d="M20 11a8 8 0 1 0 2 5.3" />
          <path d="M20 4v7h-7" />
        </svg>
      );
    case 'plus':
      return (
        <svg {...props}>
          <path d="M12 5v14M5 12h14" />
        </svg>
      );
    case 'download':
      return (
        <svg {...props}>
          <path d="M12 4v11" />
          <path d="m8 11 4 4 4-4" />
          <path d="M4 20h16" />
        </svg>
      );
    case 'upload':
      return (
        <svg {...props}>
          <path d="M12 20V9" />
          <path d="m8 13 4-4 4 4" />
          <path d="M4 4h16" />
        </svg>
      );
    case 'trash':
      return (
        <svg {...props}>
          <path d="M4 7h16" />
          <path d="M10 11v6M14 11v6" />
          <path d="M6 7l1 13h10l1-13M9 7V4h6v3" />
        </svg>
      );
    case 'edit':
      return (
        <svg {...props}>
          <path d="M12 20h9" />
          <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4Z" />
        </svg>
      );
    case 'copy':
      return (
        <svg {...props}>
          <rect x="9" y="9" width="11" height="11" rx="2" />
          <rect x="4" y="4" width="11" height="11" rx="2" />
        </svg>
      );
    case 'search':
      return (
        <svg {...props}>
          <circle cx="11" cy="11" r="6" />
          <path d="m20 20-4-4" />
        </svg>
      );
    case 'warning':
      return (
        <svg {...props}>
          <path d="m12 4 8 14H4Z" />
          <path d="M12 9v4M12 16h.01" />
        </svg>
      );
    case 'clock':
      return (
        <svg {...props}>
          <circle cx="12" cy="12" r="8" />
          <path d="M12 8v5l3 2" />
        </svg>
      );
    case 'check':
      return (
        <svg {...props}>
          <path d="m5 13 4 4L19 7" />
        </svg>
      );
    case 'x':
      return (
        <svg {...props}>
          <path d="M6 6l12 12M18 6 6 18" />
        </svg>
      );
    case 'link':
      return (
        <svg {...props}>
          <path d="M10 13a5 5 0 0 1 0-7l1-1a5 5 0 0 1 7 7l-1 1" />
          <path d="M14 11a5 5 0 0 1 0 7l-1 1a5 5 0 0 1-7-7l1-1" />
        </svg>
      );
    case 'folder':
      return (
        <svg {...props}>
          <path d="M3 6h6l2 2h10v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />
        </svg>
      );
    case 'spinner':
      return (
        <svg {...props}>
          <path d="M21 12a9 9 0 1 1-3-6.7" />
        </svg>
      );
    case 'statusOn':
      return (
        <svg {...props}>
          <circle cx="12" cy="12" r="8" />
          <path d="m8.5 12.5 2.2 2.2L15.5 10" />
        </svg>
      );
    case 'statusOff':
      return (
        <svg {...props}>
          <circle cx="12" cy="12" r="8" />
          <path d="M9.5 9.5l5 5M14.5 9.5l-5 5" />
        </svg>
      );
    default:
      return null;
  }
};
