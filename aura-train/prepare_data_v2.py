import json
import os
import random
import numpy as np
from pathlib import Path
from tokenizers import Tokenizer, models, trainers, pre_tokenizers, decoders
from datasets import load_dataset

DATA_DIR = Path(__file__).parent / "data"


def download_tinystories_full(max_stories: int = None):
    """Download TinyStories dataset."""
    print("downloading TinyStories...")
    ds = load_dataset("roneneldan/TinyStories", split="train", streaming=True)
    texts = []
    count = 0
    for example in ds:
        texts.append(example["text"])
        count += 1
        if max_stories and count >= max_stories:
            break
        if count % 50000 == 0:
            print(f"  {count} stories loaded...")
    print(f"  total: {count:,} stories")
    return "\n\n".join(texts)


def generate_chat_examples(stories_text: str, num_examples: int = 100000):
    """Generate chat-formatted training examples from story text."""
    print(f"generating {num_examples:,} chat examples...")
    stories = [s.strip() for s in stories_text.split("\n\n") if s.strip() and len(s.strip()) > 100]
    chat_examples = []

    topics = [
        "Tell me a story.", "What happened next?",
        "Can you tell me about", "Tell me something.",
        "Can you share a tale?", "What's a good story?",
        "Hello!", "Hi there!", "How are you?",
        "Tell me a tale.",
    ]

    for _ in range(num_examples):
        story = random.choice(stories)
        topic = random.choice(topics)
        max_len = min(500, len(story))
        min_len = min(50, max_len)
        reply_len = random.randint(min_len, max_len)
        assistant_reply = story[:reply_len]
        chat_text = f"User: {topic}\nAssistant: {assistant_reply}"
        chat_examples.append(chat_text)

    return "\n\n".join(chat_examples)


def train_tokenizer(texts, vocab_size=16384, save_path=None):
    """Train a BPE tokenizer with position-invariant prefix handling."""
    print(f"training BPE tokenizer (vocab_size={vocab_size})...")
    tokenizer = Tokenizer(models.BPE())
    tokenizer.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=True)
    tokenizer.decoder = decoders.ByteLevel()

    trainer = trainers.BpeTrainer(
        vocab_size=vocab_size,
        special_tokens=["<|pad|>", "<|bos|>", "<|eos|>", "<|unk|>"],
        initial_alphabet=pre_tokenizers.ByteLevel.alphabet(),
    )

    tokenizer.train_from_iterator(texts, trainer)

    if save_path:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        tokenizer.save(save_path)
        print(f"  tokenizer saved: {save_path}")

    print(f"  vocab: {tokenizer.get_vocab_size()} tokens")
    return tokenizer


def _tokenize_stream(tokenizer, texts, desc="tokenizing", batch_size=1000):
    ids = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        joined = "\n\n".join(batch)
        ids.extend(tokenizer.encode(joined).ids)
        if (i // batch_size) % 20 == 0:
            print(f"  {desc}: {i}/{len(texts)}", end="\r")
    if desc:
        print(f"  {desc}: {len(texts)}/{len(texts)} done, {len(ids):,} tokens")
    return ids


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--vocab-size", type=int, default=16384)
    parser.add_argument("--seq-len", type=int, default=256)
    parser.add_argument("--save-dir", type=str, default=str(DATA_DIR))
    parser.add_argument("--max-stories", type=int, default=None,
                        help="Limit number of TinyStories to download")
    parser.add_argument("--chat-examples", type=int, default=100000,
                        help="Number of chat-formatted examples to generate")
    parser.add_argument("--existing-tokenizer", type=str, default=None,
                        help="Path to existing tokenizer to reuse (skips training)")
    args = parser.parse_args()

    save_dir = Path(args.save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    # --- Download stories (keep as list) ---
    print("downloading TinyStories...")
    story_texts = []
    ds = load_dataset("roneneldan/TinyStories", split="train", streaming=True)
    count = 0
    for example in ds:
        story_texts.append(example["text"])
        count += 1
        if args.max_stories and count >= args.max_stories:
            break
        if count % 50000 == 0:
            print(f"  {count} stories loaded...")
    print(f"  total: {count:,} stories")

    # --- Generate chat examples (as list, sampling from stories) ---
    print(f"generating {args.chat_examples:,} chat examples...")
    valid_stories = [s.strip() for s in story_texts if s.strip() and len(s.strip()) > 100]
    topics = [
        "Tell me a story.", "What happened next?",
        "Can you tell me about", "Tell me something.",
        "Can you share a tale?", "What's a good story?",
        "Hello!", "Hi there!", "How are you?",
        "Tell me a tale.",
    ]
    chat_texts = []
    for _ in range(args.chat_examples):
        story = random.choice(valid_stories)
        topic = random.choice(topics)
        max_len = min(500, len(story))
        min_len = min(50, max_len)
        reply_len = random.randint(min_len, max_len)
        chat_texts.append(f"User: {topic}\nAssistant: {story[:reply_len]}")

    print(f"  generated {len(chat_texts):,} examples")

    # --- Tokenizer: reuse or train ---
    tokenizer_path = save_dir / "tokenizer.json"
    if args.existing_tokenizer and Path(args.existing_tokenizer).exists():
        print(f"loading existing tokenizer: {args.existing_tokenizer}")
        tokenizer = Tokenizer.from_file(str(args.existing_tokenizer))
    else:
        all_train_texts = story_texts + chat_texts
        tokenizer = train_tokenizer(all_train_texts, args.vocab_size, str(tokenizer_path))

    # --- Tokenize in streaming fashion ---
    print("\ntokenizing...")
    all_ids = _tokenize_stream(tokenizer, story_texts, "stories")
    n_story = len(all_ids)
    n_chat_pre = len(all_ids)
    chat_ids = _tokenize_stream(tokenizer, chat_texts, "chat")
    all_ids.extend(chat_ids)
    n_chat = len(chat_ids)

    print(f"  stories: {n_story:,} tokens")
    print(f"  chat: {n_chat:,} tokens")
    print(f"  total: {len(all_ids):,} tokens")

    np.save(save_dir / "tokens.npy", np.array(all_ids, dtype=np.int32))
    np.save(save_dir / "token_ids.npy", np.array(all_ids, dtype=np.int32))

    config = {
        "dataset": "tinystories+chat",
        "vocab_size": tokenizer.get_vocab_size(),
        "seq_len": args.seq_len,
        "total_tokens": len(all_ids),
    }
    with open(save_dir / "config.json", "w") as f:
        json.dump(config, f, indent=2)

    print(f"\ndata saved to {save_dir}/")
    print(f"  tokens: {len(all_ids):,}")
    print(f"  vocab_size: {tokenizer.get_vocab_size()}")
    print(f"  sample (first 20 IDs): {all_ids[:20]}")

    tokenizer_sanity_check(tokenizer)

    del story_texts, chat_texts, all_ids, valid_stories, topics


def tokenizer_sanity_check(tokenizer):
    """Verify tokenizer produces consistent tokenization."""
    print("\ntokenizer sanity check:")
    test_words = ["needle", "Hello", "User:", "Assistant:", "the", "story"]
    for word in test_words:
        ids_start = tokenizer.encode(word).ids
        ids_mid = tokenizer.encode(f"prefix {word} suffix").ids
        print(f"  {repr(word)} -> alone: {ids_start}")
        print(f"    -> in context: {ids_mid}")


if __name__ == "__main__":
    main()
