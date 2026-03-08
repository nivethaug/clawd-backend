import { Button } from '@/components/ui/button';

export default function Welcome() {
  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      <div className="text-center space-y-6 max-w-md w-full">
        <div className="w-16 h-16 mx-auto rounded-2xl bg-primary/10 flex items-center justify-center mb-4">
          <div className="w-8 h-8 rounded-md bg-primary" />
        </div>
        <h1 className="text-3xl font-bold">DreamPilot Generated App</h1>
        <p className="text-lg text-muted-foreground">Start building your application.</p>
        <Button size="lg" className="w-full">Get Started</Button>
      </div>
    </div>
  );
}