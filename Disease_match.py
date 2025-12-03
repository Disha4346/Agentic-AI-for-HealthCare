import whisper
import argparse
import os
import torch
import re
from rapidfuzz import fuzz

# ---- STEP 1: Whisper Transcription ----
def get_transcript(file_path, model_name):
    print(f"Loading Whisper model: '{model_name}'...")
    try:
        model = whisper.load_model(model_name)
    except Exception as e:
        print(f"Error loading model '{model_name}': {e}")
        return None

    if not os.path.exists(file_path):
        print(f"Error: File not found at {file_path}")
        return None

    use_fp16 = torch.cuda.is_available()
    print("GPU detected. Using FP16." if use_fp16 else "No GPU found. Using CPU (slower).")

    print(f"Transcribing: {file_path}...")
    try:
        result = model.transcribe(file_path, fp16=use_fp16)
        print("Transcription complete.")
        return result["text"]
    except Exception as e:
        print(f"Error during transcription: {e}")
        return None


# ---- STEP 2: Get Unique Words from Transcript ----
def get_transcript_words(text):
    text = text.lower()
    # Remove punctuation using regex
    text = re.sub(r"[^\w\s]", "", text)
    
    # Define common stop words to ignore (EXPANDED LIST)
    stop_words = {
        # Basic English
        "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "if", 
        "in", "is", "it", "its", "it's", "of", "on", "or", "so", "such", 
        "that", "the", "their", "then", "there", "these", "they", "this", 
        "to", "was", "with",
        
        # Pronouns / People
        "i", "me", "my", "myself", "we", "our", "ours", "ourselves", "you", 
        "your", "yours", "yourself", "yourselves", "he", "him", "his", 
        "himself", "she", "her", "hers", "herself", "they", "them", "their", 
        "theirs", "themselves",
        
        # Verbs / Modals
        "am", "been", "being", "can", "could", "did", "do", "does", "doesn't", 
        "doing", "don't", "get", "gets", "getting", "got", "gotten", "go", 
        "goes", "going", "had", "has", "hasn't", "have", "haven't", "having", 
        "is", "isn't", "make", "makes", "making", "should", "used", "was", 
        "wasn't", "were", "weren't", "will", "would",
        
        # Conversational Filler / Context
        "about", "after", "against", "all", "almost", "also", "although", 
        "always", "any", "anywhere", "because", "become", "before", "bit", 
        "chapped", "clothes", "come", "concern", "cuts", "else", "especially", 
        "even", "every", "feel", "feels", "feeling", "find", "found", "from", 
        "further", "here", "how", "however", "just", "kind", "know", "like", 
        "little", "look", "looks", "made", "many", "may", "more", "most", 
        "much", "must", "now", "noticed", "onto", "other", "over", "own", 
        "pexing", "quite", "read", "really", "see", "seen", "seem", "seemed", 
        "see", "show", "since", "skin", "small", "some", "sometimes", "soon", 
        "spot", "spread", "started", "still", "such", "than", "thank", "thanks", 
        "that's", "there", "therefore", "these", "those", "through", "time", 
        "times", "today", "too", "try", "up", "upon", "us", "very", "want", 
        "wanted", "way", "well", "what", "when", "where", "which", "while", 
        "who", "whom", "why", "work"
    }
                  
    # Split text into words, filter out stop words and short words
    all_words = text.split()
    found_keywords = {word for word in all_words if word not in stop_words and len(word) > 2}

    return sorted(found_keywords)


# ---- STEP 3: Match Extracted Keywords with Diseases (NEW LOGIC) ----
def match_disease(extracted_keywords, transcript_text, keyword_folder="keywords"):
    # This stop_tokens list is a bit redundant now but harmless
    stop_tokens = {"a", "an", "the", "is", "it", "i", "me", "my", "we", "you", "he", "she", "they", "small", "large"}
    extracted = [k for k in extracted_keywords if len(k) >= 3 and k not in stop_tokens]
    if not extracted:
        return ("NoKeywords", 0), []

    results = []
    
    # Check if keyword folder exists
    if not os.path.isdir(keyword_folder):
        print(f"Error: Keyword folder '{keyword_folder}' not found.")
        print("Please make sure the 'keywords' folder is in the same directory as the script.")
        return ("KeywordFolderNotFound", 0), []

    for file_name in os.listdir(keyword_folder):
        if not file_name.endswith(".txt"):
            continue
        disease_name = file_name.replace(".txt", "")
        
        try:
            with open(os.path.join(keyword_folder, file_name), "r", encoding="utf-8") as f:
                disease_keywords = [line.strip().lower() for line in f if line.strip()]
        except FileNotFoundError:
            print(f"Warning: Could not find file {file_name} while iterating, skipping.")
            continue
        except Exception as e:
            print(f"Error reading {file_name}: {e}")
            continue

        # --- fuzzy match average (NEW LOGIC) ---
        # Answers: "How well does the transcript cover this disease's keywords?"
        sum_best = 0.0
        
        # Filter disease keywords once
        disease_keywords_long = [dk for dk in disease_keywords if len(dk) >= 3]
        if not disease_keywords_long:
            avg_fuzzy = 0.0 # No keywords to match
        else:
            for dk in disease_keywords_long: # 'dk' is a keyword from the disease .txt file
                best = 0
                for ek in extracted: # 'ek' is a word from the transcript
                    # Use partial_ratio to find 'stuck' in 'stuck on appearance'
                    s = fuzz.partial_ratio(ek, dk)
                    if s > best:
                        best = s
                sum_best += best # Add the best possible match for this disease keyword
            
            # Average the score over the number of disease keywords
            avg_fuzzy = sum_best / len(disease_keywords_long)

        # --- exact coverage ---
        # Checks if any of the specific diagnostic phrases are present in the full transcript.
        exact_matches = 0
        for dk in disease_keywords_long:
            # Use re.search to find the keyword *anywhere* in the text
            if re.search(re.escape(dk), transcript_text):
                exact_matches += 1
                
        exact_coverage = (exact_matches / max(1, len(disease_keywords_long))) * 100.0

        # --- combine ---
        # We give fuzzy matching more weight because users rarely say the exact medical term
        final_score = 0.65 * avg_fuzzy + 0.35 * exact_coverage
        results.append((disease_name, round(final_score, 1), round(avg_fuzzy, 1), round(exact_coverage, 1)))

    if not results:
        print("No .txt files found in the 'keywords' folder.")
        return ("NoKeywordFiles", 0), []

    sorted_results = sorted(results, key=lambda x: x[1], reverse=True)
    best = (sorted_results[0][0], sorted_results[0][1]) if sorted_results else (None, 0)
    return best, sorted_results


# ---- STEP 4: Save Transcript and Keywords ----
def save_transcript_and_keywords(text, keywords, output_file):
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("--- Transcript ---\n")
            f.write(text + "\n\n")
            f.write("--- Unique Transcript Words ---\n")
            f.write(", ".join(keywords) if keywords else "No words found.")
        print(f"\nTranscript and keywords saved to: {output_file}")
    except IOError as e:
        print(f"Error saving file: {e}")


# ---- STEP 5: Main ----
def main():
    # These lines are necessary to run the script from the command line
    parser = argparse.ArgumentParser(description="Transcribe a video file and extract skin disease keywords.")
    parser.add_argument("video_path", type=str, help="Path to video/audio file.")
    parser.add_argument("--model", type=str, default="small", help="Whisper model (tiny, base, small, medium, large).")
    parser.add_argument("--output_file", type=str, help="Output text file (optional).")
    args = parser.parse_args()

    base_name = os.path.splitext(os.path.basename(args.video_path))[0]
    transcript_path = args.output_file if args.output_file else f"{base_name}.txt"

    transcript_text = get_transcript(args.video_path, args.model)

    if transcript_text:
        # ---- THIS IS THE UPDATED LINE ----
        keywords = get_transcript_words(transcript_text)
        
        print(f"\n--- Found {len(keywords)} Unique Transcript Words (for matching) ---")
        print(keywords)

        best_match, all_scores = match_disease(keywords, transcript_text, keyword_folder="keywords")

        print(f"\n--- Most Likely Disease ---")
        print(f"{best_match[0]} (Match Score: {best_match[1]}%)")

        print("\n--- All Disease Scores ---")
        for disease, final_score, avg_fuzzy, exact_cov in all_scores:
            # Corrected the typo here
            print(f"{disease}: {final_score}%  (fuzzy={avg_fuzzy}, exact={exact_cov})")

        save_transcript_and_keywords(transcript_text, keywords, transcript_path)
    else:
        print("No transcript generated.")


if __name__ == "__main__":
    main()

