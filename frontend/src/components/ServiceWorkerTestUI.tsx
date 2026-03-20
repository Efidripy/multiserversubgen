/**
 * UI компонент для тестирования Service Worker
 */
import React, { useState } from 'react';
import { ServiceWorkerTester, ServiceWorkerTestResult } from '../services/swTester';

export const ServiceWorkerTestUI: React.FC = () => {
  const [results, setResults] = useState<ServiceWorkerTestResult[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  const runTests = async () => {
    setIsRunning(true);
    const tester = new ServiceWorkerTester();
    const testResults = await tester.runAllTests();
    setResults(testResults);
    setIsRunning(false);

    // Вывести отчет в консоль
    console.log(tester.getReport());
  };

  const passedCount = results.filter((r) => r.passed).length;
  const totalCount = results.length;

  return (
    <div style={{ padding: '1.5rem', fontFamily: 'system-ui', backgroundColor: '#f9fafb', borderRadius: '0.5rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <h3 style={{ margin: 0 }}>⚙️ Тестирование Service Worker</h3>
        <button
          onClick={runTests}
          disabled={isRunning}
          style={{
            padding: '0.5rem 1rem',
            backgroundColor: isRunning ? '#9ca3af' : '#3b82f6',
            color: 'white',
            border: 'none',
            borderRadius: '0.375rem',
            cursor: isRunning ? 'default' : 'pointer',
            fontWeight: 'bold',
          }}
        >
          {isRunning ? '⏳ Тестирование...' : '▶️ Запустить тесты'}
        </button>
      </div>

      {results.length > 0 && (
        <>
          <div
            style={{
              display: 'flex',
              gap: '1rem',
              marginBottom: '1.5rem',
              padding: '1rem',
              backgroundColor: passedCount === totalCount ? '#d1fae5' : '#fef3c7',
              borderRadius: '0.375rem',
              border: `2px solid ${passedCount === totalCount ? '#10b981' : '#f59e0b'}`,
            }}
          >
            <div>
              <div style={{ fontSize: '0.875rem', color: '#666' }}>Результат:</div>
              <div style={{ fontSize: '1.5rem', fontWeight: 'bold' }}>
                {passedCount}/{totalCount} пройдено
              </div>
            </div>
            <div style={{ flex: 1 }}>
              <div
                style={{
                  width: '100%',
                  height: '0.5rem',
                  backgroundColor: '#e5e7eb',
                  borderRadius: '0.25rem',
                  overflow: 'hidden',
                  marginTop: '0.5rem',
                }}
              >
                <div
                  style={{
                    width: `${((passedCount / totalCount) * 100).toFixed(0)}%`,
                    height: '100%',
                    backgroundColor: passedCount === totalCount ? '#10b981' : '#f59e0b',
                    transition: 'width 0.3s ease',
                  }}
                />
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {results.map((result, idx) => {
              const isExpanded = expanded === result.name;
              const statusIcon = result.passed ? '✅' : result.name.includes('⚠️') ? '⚠️' : '❌';

              return (
                <div
                  key={idx}
                  style={{
                    border: `1px solid ${result.passed ? '#d1d5db' : '#fca5a5'}`,
                    borderRadius: '0.375rem',
                    backgroundColor: result.passed ? '#f3f4f6' : '#fef2f2',
                    overflow: 'hidden',
                  }}
                >
                  <div
                    onClick={() => setExpanded(isExpanded ? null : result.name)}
                    style={{
                      padding: '0.75rem 1rem',
                      cursor: 'pointer',
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      backgroundColor: result.passed ? '#f9fafb' : '#fef2f2',
                    }}
                  >
                    <span style={{ fontWeight: '500' }}>
                      {statusIcon} {result.name}
                    </span>
                    <span style={{ fontSize: '0.875rem', color: '#999' }}>
                      {result.duration.toFixed(2)}ms {isExpanded ? '▼' : '▶'}
                    </span>
                  </div>

                  {isExpanded && (
                    <div style={{ padding: '0.75rem 1rem', borderTop: '1px solid #e5e7eb', backgroundColor: 'white' }}>
                      {result.message && (
                        <div style={{ marginBottom: '0.5rem', color: '#dc2626' }}>
                          <strong>Сообщение:</strong> {result.message}
                        </div>
                      )}
                      {result.details && (
                        <div style={{ marginBottom: '0.5rem' }}>
                          <strong>Детали:</strong>
                          <pre
                            style={{
                              backgroundColor: '#f3f4f6',
                              padding: '0.5rem',
                              borderRadius: '0.25rem',
                              fontSize: '0.875rem',
                              overflow: 'auto',
                              margin: '0.5rem 0 0 0',
                            }}
                          >
                            {JSON.stringify(result.details, null, 2)}
                          </pre>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}

      {results.length === 0 && !isRunning && (
        <div style={{ textAlign: 'center', color: '#999', padding: '2rem 0' }}>
          📋 Щелкните "Запустить тесты" для проверки Service Worker функций
        </div>
      )}
    </div>
  );
};

export default ServiceWorkerTestUI;
