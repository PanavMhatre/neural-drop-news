"""
Script structure templates for variation.

Defines different script formats that rotate across videos to prevent
repetitive content and keep the channel feeling fresh.
"""

from dataclasses import dataclass

from src.models.schemas import ScriptStructureType


@dataclass
class ScriptStructure:
    """A script structure template."""
    type: ScriptStructureType
    name: str
    hook_template: str
    flow_description: str
    example_hook: str
    system_instruction: str


# All available script structures
SCRIPT_STRUCTURES: dict[ScriptStructureType, ScriptStructure] = {
    ScriptStructureType.SOUNDS_BORING_BUT: ScriptStructure(
        type=ScriptStructureType.SOUNDS_BORING_BUT,
        name="Sounds Boring But...",
        hook_template="This sounds boring, but it matters because…",
        flow_description="Start with what seems uninteresting, then reveal the hidden significance",
        example_hook="A database update sounds boring — until you realize it could kill half the coding tools you use.",
        system_instruction="""Structure the script as:
1. Hook: Present the story as seemingly boring or unimportant
2. Pivot: Reveal why it actually matters a lot
3. Explanation: Break down the real impact
4. Student/dev angle: What this means for your career or learning
5. Close: Punchy takeaway that reinforces the surprise"""
    ),

    ScriptStructureType.EVERYONE_MISSED: ScriptStructure(
        type=ScriptStructureType.EVERYONE_MISSED,
        name="Everyone Missed This",
        hook_template="Everyone missed the important part…",
        flow_description="Focus on the overlooked detail in a bigger story",
        example_hook="Everyone's talking about GPT-5, but nobody noticed what OpenAI buried in the fine print.",
        system_instruction="""Structure the script as:
1. Hook: Point out what everyone is focused on (the headline)
2. Redirect: Reveal the overlooked detail
3. Explanation: Why that detail is actually the real story
4. Impact: What this means going forward
5. Close: Challenge the viewer to think differently"""
    ),

    ScriptStructureType.WHAT_ACTUALLY_HAPPENED: ScriptStructure(
        type=ScriptStructureType.WHAT_ACTUALLY_HAPPENED,
        name="What Actually Happened",
        hook_template="Here's what actually happened…",
        flow_description="Cut through hype/confusion to explain the real story",
        example_hook="Nvidia didn't just launch a chip. Here's what actually happened and why Wall Street is freaking out.",
        system_instruction="""Structure the script as:
1. Hook: Reference the confusing/hyped headline
2. Reality: Explain what actually happened in plain terms
3. Context: Why it matters more (or less) than people think
4. Practical angle: What this means for people building/learning
5. Close: Clear, grounded takeaway"""
    ),

    ScriptStructureType.GOOD_BAD_NEWS: ScriptStructure(
        type=ScriptStructureType.GOOD_BAD_NEWS,
        name="Good/Bad News For Students",
        hook_template="This is good/bad news for students because…",
        flow_description="Frame the story directly through the student/dev lens",
        example_hook="If you're a CS student, this is really good news. Here's why.",
        system_instruction="""Structure the script as:
1. Hook: Directly address students/developers with good or bad news framing
2. The news: What happened, explained simply
3. Why it's good/bad: Direct impact on students, job seekers, or learners
4. What to do: Actionable advice or perspective
5. Close: Encouraging or motivating ending"""
    ),

    ScriptStructureType.COMPANY_MOVE: ScriptStructure(
        type=ScriptStructureType.COMPANY_MOVE,
        name="Company Strategic Move",
        hook_template="This company just made a move that tells us where tech is going…",
        flow_description="Analyze a company's strategy and what it signals for the industry",
        example_hook="Google just made a move that tells us exactly where AI is heading in 2026.",
        system_instruction="""Structure the script as:
1. Hook: Name the company and tease the strategic significance
2. The move: What they did, in plain terms
3. Strategy: Why they did it (business logic)
4. Industry signal: What this tells us about where tech is heading
5. Close: What builders and students should pay attention to"""
    ),

    ScriptStructureType.LEARNING_TO_CODE: ScriptStructure(
        type=ScriptStructureType.LEARNING_TO_CODE,
        name="If You're Learning to Code",
        hook_template="If you're learning to code, pay attention to this…",
        flow_description="Frame a story specifically for people learning software development",
        example_hook="If you're learning to code right now, you need to know about this.",
        system_instruction="""Structure the script as:
1. Hook: Directly speak to learners/aspiring developers
2. The news: What happened, simplified for beginners
3. Why it matters for learning: How this affects what/how to learn
4. Practical advice: What to do differently based on this news
5. Close: Motivating message for learners"""
    ),

    ScriptStructureType.HEADLINE_VS_REALITY: ScriptStructure(
        type=ScriptStructureType.HEADLINE_VS_REALITY,
        name="Headline vs Reality",
        hook_template="The headline is X, but the real story is Y…",
        flow_description="Contrast the misleading headline with the actual reality",
        example_hook="The headline says AI will replace all programmers. The real story is way more interesting.",
        system_instruction="""Structure the script as:
1. Hook: State the dramatic/misleading headline
2. Reality check: What the headline gets wrong or oversimplifies
3. The real story: What's actually happening
4. Nuance: Why this matters more (or less) than the headline suggests
5. Close: Balanced, informed perspective"""
    ),
}


def get_all_structure_types() -> list[str]:
    """Get all available structure type values."""
    return [s.value for s in ScriptStructureType]


def get_structure(structure_type: ScriptStructureType) -> ScriptStructure:
    """Get a specific script structure template."""
    return SCRIPT_STRUCTURES[structure_type]


def get_structure_by_name(name: str) -> ScriptStructure:
    """Get a structure by its enum value string."""
    return SCRIPT_STRUCTURES[ScriptStructureType(name)]
