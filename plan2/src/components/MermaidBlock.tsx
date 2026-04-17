import { useEffect, useId, useState } from 'react';

declare global {
  interface Window {
    mermaid?: {
      initialize: (config: Record<string, unknown>) => void;
      run: (options?: { nodes?: Element[] | NodeListOf<Element> | null }) => Promise<void>;
    };
    __mermaidLoaderPromise?: Promise<void>;
    __mermaidInitialized?: boolean;
  }
}

function ensureMermaidLoaded(): Promise<void> {
  if (window.mermaid) {
    return Promise.resolve();
  }

  if (window.__mermaidLoaderPromise) {
    return window.__mermaidLoaderPromise;
  }

  window.__mermaidLoaderPromise = new Promise<void>((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js';
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error('Failed to load Mermaid script'));
    document.head.appendChild(script);
  });

  return window.__mermaidLoaderPromise;
}

type MermaidBlockProps = {
  chart: string;
};

const MermaidBlock: React.FC<MermaidBlockProps> = ({ chart }) => {
  const [error, setError] = useState<string | null>(null);
  const elementId = useId().replace(/:/g, '_');

  useEffect(() => {
    let cancelled = false;

    const renderChart = async () => {
      try {
        setError(null);
        await ensureMermaidLoaded();
        if (!window.mermaid || cancelled) return;

        if (!window.__mermaidInitialized) {
          window.mermaid.initialize({
            startOnLoad: false,
            securityLevel: 'loose',
            theme: 'default',
            flowchart: {
              useMaxWidth: true,
              htmlLabels: true,
              curve: 'basis',
            },
          });
          window.__mermaidInitialized = true;
        }

        const node = document.getElementById(elementId);
        if (!node || cancelled) return;
        node.textContent = chart;
        await window.mermaid.run({ nodes: [node] });
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to render Mermaid chart');
        }
      }
    };

    void renderChart();
    return () => {
      cancelled = true;
    };
  }, [chart, elementId]);

  if (error) {
    return (
      <pre className="mermaid-fallback">
        <code>{chart}</code>
      </pre>
    );
  }

  return <div id={elementId} className="mermaid-block">{chart}</div>;
};

export default MermaidBlock;
