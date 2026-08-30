import { AlertTriangle, LoaderCircle } from 'lucide-react'

export function LoadingState({ label = 'Updating decision' }: { label?: string }) {
  return <div className="inline-state" role="status"><LoaderCircle className="spin" size={17} /> {label}</div>
}

export function ErrorState({ message }: { message: string }) {
  return <div className="error-state" role="alert"><AlertTriangle size={18} /><div><strong>Unable to complete this request</strong><span>{message}</span></div></div>
}
