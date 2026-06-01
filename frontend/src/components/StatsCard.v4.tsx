import React from 'react';

interface StatsCardProps {
  title: string;
  value: string;
  icon: React.ReactNode;
  gradient?: string;
  shadowColor?: string;
  onClick?: () => void;
  disabled?: boolean;
}

export const StatsCardV4: React.FC<StatsCardProps> = ({
  title,
  value,
  icon,
  gradient = 'from-cyan-400/80 to-blue-400/80',
  shadowColor = 'shadow-cyan-400/20',
  onClick,
  disabled = false,
}) => {
  return (
    <div
      onClick={onClick}
      className={`bg-[#0f1420] backdrop-blur-sm border border-cyan-500/20 rounded-lg p-4 hover:border-cyan-400/30 transition-all relative overflow-hidden group ${
        onClick && !disabled ? 'cursor-pointer' : ''
      }`}
    >
      <div className={`w-10 h-10 bg-gradient-to-br ${gradient} rounded-lg flex items-center justify-center mb-3 shadow-lg ${shadowColor} relative flex-shrink-0`}>
        <div className="text-white">
          {icon}
        </div>
      </div>

      <p className="text-gray-400 text-[10px] font-mono uppercase mb-1">{title}</p>
      <p className="text-2xl font-bold text-white font-mono">{value}</p>
    </div>
  );
};
