"""
Test chatbot trực tiếp trên terminal.
Chạy: python test_chat.py
"""

import asyncio
import os
import sys

from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text
from rich import box

load_dotenv()

import claude_client
import knowledge_base

console = Console()


def print_header():
    console.print()
    console.print(Panel(
        "[bold green]CHATBOT CA CHUA[/bold green]\n"
        "[dim]Tư vấn kỹ thuật trồng cà chua cho nông dân Việt Nam[/dim]\n"
        "[dim]Gõ 'thoat' để dừng[/dim]",
        box=box.DOUBLE,
        border_style="green",
        padding=(1, 4),
    ))
    console.print()


def print_user(text: str):
    console.print(Panel(
        f"[bold white]{text}[/bold white]",
        title="[cyan]Ban[/cyan]",
        border_style="cyan",
        box=box.ROUNDED,
        padding=(0, 2),
    ))


def print_bot(text: str):
    console.print(Panel(
        Markdown(text),
        title="[green]Chuyen gia ca chua[/green]",
        border_style="green",
        box=box.ROUNDED,
        padding=(1, 2),
    ))


async def chat():
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        console.print("[bold red]LOI:[/bold red] Chua co OPENROUTER_API_KEY trong file .env")
        sys.exit(1)

    print_header()

    while True:
        try:
            question = Prompt.ask("[cyan]Ban[/cyan]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Tam biet![/dim]")
            break

        if not question:
            continue
        if question.lower() in ("thoat", "quit", "exit"):
            console.print("[dim]Tam biet![/dim]")
            break

        print_user(question)

        with console.status("[green]Dang suy nghi...[/green]", spinner="dots"):
            context = knowledge_base.search(question)
            try:
                answer = await claude_client.ask(question=question, context=context)
            except Exception as e:
                answer = f"Loi he thong: {e}"

        print_bot(answer)
        console.print()


if __name__ == "__main__":
    asyncio.run(chat())
