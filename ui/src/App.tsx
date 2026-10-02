export function App({ hasToken }: { hasToken: boolean }) {
  return (
    <main className="mx-auto max-w-2xl p-8 font-sans">
      <h1 className="text-2xl font-semibold">dsj</h1>
      {hasToken ? (
        <p className="mt-4 text-muted-foreground">The library is empty.</p>
      ) : (
        <p className="mt-4">
          This page was opened without its key. Open the address <code>dsj ui</code> printed in
          the terminal, including the part after <code>#</code>.
        </p>
      )}
    </main>
  );
}
