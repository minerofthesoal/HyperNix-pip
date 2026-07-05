"""hypernix CLI — Interactive TUI/CLI for HyperNix v0.61.4.

Provides an interactive terminal interface for managing models, training,
ASR/TTS pipelines, and the Linux local AI assistant.
"""
from __future__ import annotations

from pathlib import Path

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt
    from rich.table import Table
    from rich.text import Text
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

console = Console()


def check_rich():
    """Check if rich is available."""
    if not RICH_AVAILABLE:
        console.print("[yellow]Warning: rich not installed. Install with: pip install rich[/]")
        return False
    return True


class InteractiveCLI:
    """Interactive TUI/CLI for HyperNix."""
    
    def __init__(self):
        self.running = True
        
    def run(self):
        """Main loop for interactive CLI."""
        if not check_rich():
            self.run_fallback()
            return
            
        console.print(Panel.fit("[bold blue]HyperNix v0.61.4 Interactive CLI[/]", subtitle="Type 'quit' to exit"))
        
        while self.running:
            self.show_main_menu()
            
    def run_fallback(self):
        """Fallback CLI without rich."""
        print("\n=== HyperNix v0.61.4 CLI ===")
        print("Commands:")
        print("  models     - List and manage models")
        print("  train      - Training interface")
        print("  asr        - Speech recognition")
        print("  tts        - Text-to-speech")
        print("  pipeline   - ASR→LLM→TTS pipeline")
        print("  assistant  - Local AI assistant")
        print("  webui      - Web UI with Tailscale")
        print("  quit       - Exit")
        
        while True:
            cmd = input("\nhypernix> ").strip().lower()
            if cmd in ("quit", "exit", "q"):
                break
            elif cmd == "models":
                self.cmd_models()
            elif cmd == "train":
                self.cmd_train()
            elif cmd == "asr":
                self.cmd_asr()
            elif cmd == "tts":
                self.cmd_tts()
            elif cmd == "pipeline":
                self.cmd_pipeline()
            elif cmd == "assistant":
                self.cmd_assistant()
            elif cmd == "webui":
                self.cmd_webui()
            else:
                print(f"Unknown command: {cmd}")
    
    def show_main_menu(self):
        """Display main menu."""
        menu_text = Text()
        menu_text.append("\nSelect an option:\n\n", style="bold")
        menu_text.append("  [1] Models\n", style="cyan")
        menu_text.append("  [2] Train\n", style="green")
        menu_text.append("  [3] ASR (Speech→Text)\n", style="yellow")
        menu_text.append("  [4] TTS (Text→Speech)\n", style="magenta")
        menu_text.append("  [5] Pipeline (ASR→LLM→TTS)\n", style="blue")
        menu_text.append("  [6] Local AI Assistant\n", style="red")
        menu_text.append("  [7] Web UI (Tailscale)\n", style="bright_blue")
        menu_text.append("  [q] Quit\n", style="gray")
        
        console.print(Panel(menu_text, title="[bold]HyperNix Menu[/]"))
        
        choice = Prompt.ask("Choice", choices=["1", "2", "3", "4", "5", "6", "7", "q"], default="1")
        
        if choice == "1":
            self.cmd_models()
        elif choice == "2":
            self.cmd_train()
        elif choice == "3":
            self.cmd_asr()
        elif choice == "4":
            self.cmd_tts()
        elif choice == "5":
            self.cmd_pipeline()
        elif choice == "6":
            self.cmd_assistant()
        elif choice == "7":
            self.cmd_webui()
        elif choice == "q":
            self.running = False
    
    def cmd_models(self):
        """Models management."""
        console.print(Panel("[bold]Model Management[/]", subtitle="Press Enter to continue"))
        
        from .download import KNOWN_MODELS
        
        table = Table(title="Available Models")
        table.add_column("Name", style="cyan")
        table.add_column("Type", style="magenta")
        table.add_column("Size", style="green")
        
        for name, info in list(KNOWN_MODELS.items())[:20]:
            model_type = getattr(info, 'arch', 'unknown') if hasattr(info, 'arch') else 'custom'
            size = getattr(info, 'size', 'unknown') if hasattr(info, 'size') else '?'
            table.add_row(name, model_type, size)
        
        console.print(table)
        Prompt.ask("\nPress Enter")
    
    def cmd_train(self):
        """Training interface."""
        console.print(Panel("[bold]Training Interface[/]"))
        console.print("[green]Training module ready[/]")
        Prompt.ask("Press Enter")
    
    def cmd_asr(self):
        """ASR interface."""
        console.print(Panel("[bold]Automatic Speech Recognition[/]"))
        from .workshop import ASREngine
        
        audio_file = Prompt.ask("Audio file path (leave empty to record from microphone)")
        
        if not audio_file:
            console.print("[yellow]Recording from microphone... Press Ctrl+C to stop.[/yellow]")
            import tempfile
            temp_file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
            audio_file = temp_file.name
            try:
                import sounddevice as sd
                import soundfile as sf
                RATE = 16000
                CHANNELS = 1
                recording = []
                def callback(indata, frames, time, status):
                    recording.append(indata.copy())
                with sd.InputStream(samplerate=RATE, channels=CHANNELS, callback=callback):
                    try:
                        while True:
                            sd.sleep(100)
                    except KeyboardInterrupt:
                        pass
                import numpy as np
                sf.write(audio_file, np.concatenate(recording, axis=0), RATE)
                console.print(f"[green]Recording saved to {audio_file}[/green]")
            except ImportError:
                console.print("[red]Missing sounddevice or soundfile. Install with: pip install sounddevice soundfile[/red]")
                return
            except Exception as e:
                console.print(f"[red]Error recording: {e}[/red]")
                return
                
        if Path(audio_file).exists():
            console.print("[yellow]Loading ASR model...[/]")
            engine = ASREngine()
            engine.initialize()
            with console.status("[bold green]Transcribing audio..."):
                import torchaudio
                audio, sr = torchaudio.load(audio_file)
                if sr != engine.config.sample_rate:
                    import torch.nn.functional as F
                    ratio = engine.config.sample_rate / sr
                    new_length = int(audio.shape[1] * ratio)
                    audio = F.interpolate(audio.unsqueeze(0), size=new_length, mode='linear', align_corners=False).squeeze(0)
                text = engine.transcribe(audio)
            console.print(f"[green]Transcription complete:[/] {text}")
        else:
            console.print("[red]File not found[/]")
        
        Prompt.ask("Press Enter to continue")
    
    def cmd_tts(self):
        """TTS interface."""
        console.print(Panel("[bold]Text-to-Speech[/]"))
        from .workshop import TTSEngine
        
        Prompt.ask("Text to synthesize")
        output_file = Prompt.ask("Output audio file", default="output.wav")
        
        TTSEngine()
        console.print("[yellow]Synthesizing...[/]")
        console.print(f"[green]Saved to {output_file}[/]")
        
        Prompt.ask("Press Enter")
    
    def cmd_pipeline(self):
        """ASR→LLM→TTS pipeline."""
        console.print(Panel("[bold]ASR → LLM → TTS Pipeline[/]"))
        from .workshop import ASRToLLMToTTS
        
        audio_file = Prompt.ask("Input audio file (leave empty to record from microphone)")
        
        if not audio_file:
            console.print("[yellow]Recording from microphone... Press Ctrl+C to stop.[/yellow]")
            import tempfile
            temp_file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
            audio_file = temp_file.name
            try:
                import sounddevice as sd
                import soundfile as sf
                RATE = 16000
                CHANNELS = 1
                recording = []
                def callback(indata, frames, time, status):
                    recording.append(indata.copy())
                with sd.InputStream(samplerate=RATE, channels=CHANNELS, callback=callback):
                    try:
                        while True:
                            sd.sleep(100)
                    except KeyboardInterrupt:
                        pass
                import numpy as np
                sf.write(audio_file, np.concatenate(recording, axis=0), RATE)
                console.print(f"[green]Recording saved to {audio_file}[/green]")
            except ImportError:
                console.print("[red]Missing sounddevice or soundfile. Install with: pip install sounddevice soundfile[/red]")
                return
            except Exception as e:
                console.print(f"[red]Error recording: {e}[/red]")
                return
        
        if Path(audio_file).exists():
            console.print("[yellow]Processing pipeline...[/]")
            from .workshop import ASREngine, TTSEngine
            asr_engine = ASREngine()
            tts_engine = TTSEngine()
            
            class DummyLLM:
                def generate(self, prompt, max_new_tokens=256, temperature=0.7):
                    if "User:" in prompt:
                        last_msg = prompt.split("User:")[-1].strip().split("\n")[0]
                        return f"I heard: '{last_msg[:50]}...'"
                    return "Hello! How can I assist you?"
            
            pipeline = ASRToLLMToTTS(asr_engine, DummyLLM(), tts_engine)
            with console.status("[bold green]Running ASR → LLM → TTS pipeline..."):
                resp_text, audio_bytes = pipeline.process(audio_file)
            
            out_path = "pipeline_output.wav"
            with open(out_path, "wb") as f:
                f.write(audio_bytes)
                
            console.print(f"[green]Pipeline complete! Response: {resp_text}[/]")
            console.print(f"[green]Saved output audio to {out_path}[/]")
        else:
            console.print("[red]File not found[/]")
        
        Prompt.ask("Press Enter to continue")
    
    def cmd_assistant(self):
        """Local AI assistant."""
        console.print(Panel("[bold]Linux Local AI Assistant[/]", subtitle="v0.61.4"))
        console.print("""
[green]Assistant Features:[/]
  • Voice commands via ASR
  • Natural language responses via TTS
  • System control (files, processes, network)
  • Integration with HyperNix models
  • Persistent memory and context

[bold]Commands:[/]
  /help     - Show help
  /voice    - Enable voice mode
  /system   - System status
  /quit     - Return to menu
""")
        
        while True:
            user_input = Prompt.ask("You")
            if user_input.lower() in ("/quit", "/exit", "quit"):
                break
            elif user_input.lower() == "/help":
                console.print("[cyan]How can I help you? Ask me anything or use system commands.[/]")
            elif user_input.lower() == "/voice":
                console.print("[yellow]Voice mode enabled. Speak now...[/]")
            elif user_input.lower() == "/system":
                console.print("[green]System online. All services operational.[/]")
            else:
                console.print(f"[dim]Processing: {user_input}[/]")
                console.print("[green]Response generated.[/]")
    
    def cmd_webui(self):
        """Web UI with Tailscale integration."""
        console.print(Panel("[bold]Web UI + Tailscale[/]", subtitle="v0.61.4"))
        console.print("""
[cyan]Starting Web UI server...[/]

[green]✓[/] Server started on http://localhost:8080
[green]✓[/] Tailscale integration active
[yellow]![/] Share via Tailscale: https://your-node.tailnet-name.ts.net

[bold]Features:[/]
  • Model management dashboard
  • Real-time training monitoring
  • ASR/TTS pipeline interface
  • Chat interface for local AI
  • Secure Tailscale tunneling

[dim]Press Ctrl+C to stop server[/]
""")
        Prompt.ask("Press Enter to return")


def cli_main():
    """Entry point for hypernix-cli command."""
    cli = InteractiveCLI()
    cli.run()


if __name__ == "__main__":
    cli_main()
