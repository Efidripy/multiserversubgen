import React from 'react';

interface EmptyStateProps {
  icon?: string;
  title: string;
  hint?: string;
  action?: { label: string; onClick: () => void };
}

const EmptyState: React.FC<EmptyStateProps> = ({ icon = '○', title, hint, action }) => {
  return (
    <div className="empty-state">
      <span className="icon-badge icon-badge--neutral icon-badge--rounded icon-badge--lg empty-state__icon">
        {icon}
      </span>
      <div className="empty-state__title">{title}</div>
      {hint && <div className="empty-state__hint">{hint}</div>}
      {action && (
        <button className="btn btn-sm btn-ghost-accent mt-2" onClick={action.onClick}>
          {action.label}
        </button>
      )}
    </div>
  );
};

export default EmptyState;
