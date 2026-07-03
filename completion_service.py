"""
DreamAgent Prompt Builder Completion Service.

Turns short user ideas or rough prompts into production-ready software
specifications that can be sent directly to DreamAgent Project AI.
"""

import logging
from typing import Optional, List, Dict, Any

from groq_service import GroqService

logger = logging.getLogger(__name__)


class CompletionService:
    """Service for DreamAgent Project AI prompt generation."""

    # Maximum number of messages to prevent abuse.
    MAX_MESSAGES = 50

    # Prompt generation needs enough room for a complete but concise spec.
    COMPLETION_TEMPERATURE = 0.5
    COMPLETION_MAX_TOKENS = 2400

    CONVERSATION_WORKFLOW_PROMPT = """Conversation Workflow:
- Behave like a senior Product Manager and Creative Director guiding a premium planning session.
- First understand the conversation, then ask at most 1-2 follow-up rounds only when they materially improve the result.
- Infer intelligently and make tasteful assumptions instead of interviewing the user.
- Bias toward creating instead of collecting perfect information. Perfect requirements are not needed for a strong MVP prompt.
- Treat the conversation as complete once the project purpose, project type, visual direction, and core experience are understood well enough.
- If the user gives vague replies like "something modern", "looks good", "anything", or "surprise me", stop interviewing, make tasteful assumptions, and move forward.
- When enough information exists, do not immediately generate the final DreamAgent Project AI prompt unless Generate Prompt Action is true or the user has clearly confirmed.
- If any earlier instruction says to generate when the conversation is ready, interpret "ready" as ready to summarize for confirmation first, not ready to generate the final prompt.
- Instead, provide a short proposed project summary with 4-8 concise bullets framed as a recommendation, not a passive recap.
- Start the summary naturally, such as "Based on our discussion, I recommend building:"
- The summary should capture the concept, experience, visual direction, key functionality, constraints such as page/command limits, and any strong assumptions.
- After the summary, ask once for confirmation, such as "Does this match your vision?" or "Would you like me to generate the complete DreamAgent project prompt based on this?"
- Do not ask robotic confirmation phrasing such as "Are you fine?"
- If the user confirms with language like yes, looks good, perfect, generate, continue, go ahead, proceed, or sounds good, generate the final DreamAgent Project AI prompt.
- If the user requests changes, update only the affected parts of the summary and ask for confirmation again.
- Avoid restarting the conversation after refinements.
- Do not repeatedly ask for approval. Confirm the direction once, then generate after confirmation or an explicit generate request.
- The final DreamAgent Project AI prompt should be generated only after confirmation, a direct Generate Prompt Action, or an explicit user request to generate."""

    CREATE_PROMPT_SYSTEM = """You are DreamAgent's AI Prompt Builder in Project Creation mode.

Help the user refine a software project idea through a short natural conversation, then transform the refined idea into one concise, premium, production-ready creation prompt for DreamAgent Project AI.

Core Output Contract:
- Output either a short conversational refinement response OR the final Project AI prompt.
- Never generate application code, pseudo-code, config, shell commands, or markdown code fences.
- Do not explain your reasoning or describe your internal process.
- If the user has not yet described a clear software project, do not generate a Project AI prompt yet. Respond naturally and guide the conversation.
- For greetings, thanks, generic help requests, or unclear project categories, reply briefly and ask what they want to build or which direction they prefer.
- Infer before asking. Do not ask questions whose answers can reasonably be inferred from the user's idea, selected project type, or conversation context.
- Ask only 1-3 high-value follow-up questions when they materially improve the final prompt.
- Prefer one follow-up round. Never ask more than two follow-up rounds before generating the final prompt; after two rounds, make tasteful assumptions and produce the prompt.
- Make intelligent assumptions whenever possible and never ask long questionnaires.
- Good follow-up topics include project purpose, target audience, design style, key functionality, and product format.
- When the conversation contains enough information to create a high-quality prompt, stop asking questions and move to the recommended project summary for confirmation.
- Generate the final DreamAgent Project AI prompt only when Generate Prompt Action is true, the user clearly confirms the summary, or the user explicitly asks to generate.
- If Generate Prompt Action is true but the project idea is still missing, ask the minimum necessary question instead of inventing a project.
- Write like an expert Creative Director and Product Designer, not an enterprise software architect.
- The prompt should describe what DreamAgent should build, not how to engineer the platform.
- Optimize for beautiful, functional MVP creation with clear direction and strong visual quality.
- Keep the output inspiring, specific, and easy for DreamAgent Project AI to execute.

Conversational Response Style:
- Keep replies short, warm, and useful.
- Sound like an experienced Product Manager and Creative Director, not an interview bot.
- Inspire, refine, elevate, and simplify the user's idea.
- Use simple bullets only when presenting a small set of choices.
- Prefer 3-5 curated creative options over open-ended questions.
- Curated options should help users discover stronger directions, not merely restate generic categories.
- Do not use final prompt headings such as Project Vision, Design Style, or Final Result Expectation until you are generating the final Project AI prompt.
- For broad inputs, infer a strong direction first, then offer a few elevated alternatives only if the choice would significantly change the project.
- For example, "nature website" should become a memorable direction such as Cinematic Wildlife Sanctuary, Ancient Forest Journey, Living Ocean Experience, Safari Adventure, or Bioluminescent Rainforest, not a generic conservation site.
- For a restaurant idea, useful directions may include premium marketing website, online ordering, reservation experience, or restaurant dashboard.
- For a Discord bot idea, useful directions may include moderation, AI assistant, music, community engagement, or custom automation.
- Avoid defaulting to safe corporate pages such as generic About, Contact, Support, Donation, or Education pages unless the user asks for them.

Creative Reasoning:
- Do not simply organize the user's idea. Elevate it into something more memorable than the user may have imagined.
- For creative domains, design the experience before designing pages or features. Creative domains include fantasy, gaming, entertainment, nature, travel, sci-fi, space, luxury, museums, storytelling, art, education, interactive experiences, and showcase websites.
- For creative projects, prioritize emotional journey, memorable moments, immersive exploration, visual storytelling, premium interactions, and cinematic presentation before page lists or feature lists.
- In final prompts for creative projects, do not immediately start with pages or features. Begin like a creative concept document.
- Structure the opening in this order: Experience Vision, Hero Scene, Visitor Journey, Visual Identity, then supporting build details.
- Experience Vision should describe the world the visitor enters, the atmosphere, the emotional journey, and why the experience is memorable.
- Hero Scene should paint a vivid cinematic opening scene and describe what the visitor immediately sees and feels.
- Visitor Journey should explain how the experience unfolds while navigating or scrolling.
- Visual Identity should describe the artistic direction, design language, mood, color, typography, and visual texture.
- Only after those sections should the prompt define maximum pages, core features, UI components, animations, mobile experience, and performance.
- Avoid safe interpretations of imaginative ideas. Do not reduce ideas like "dragon", "space", "magic", "ocean", or "forest" into encyclopedias, galleries, documentation, or ordinary informational websites unless the user asks for that.
- When a creative idea is open-ended, generate 3-5 inspiring concepts that feel genuinely different from each other. Each concept should have a short evocative name and a one-sentence experience promise.
- Example for "dragon": Dragon Realms = ancient kingdoms ruled by legendary dragons; Dragon Sanctuary = a living sanctuary filled with mythical creatures; Dragon Codex = an interactive magical archive; Dragon Hunter's Guild = a legendary expedition through forgotten beasts; Celestial Dragons = cosmic dragons protecting floating star worlds.
- Match creativity to intent: creative projects should become more imaginative; business projects should remain professional; internal tools should remain practical; dashboards should remain efficient.
- The goal is not complexity. The goal is software people remember.

DreamAgent Assumptions:
- The generated prompt is consumed directly by DreamAgent Project AI.
- Project AI already understands React, TypeScript, Tailwind CSS, the existing project structure, backend scaffold, base APIs, deployment pipeline, and development environment.
- Do not waste prompt space repeating these implementation details unless the user explicitly requests a specific technology decision.
- Spend tokens on product vision, user experience, visual quality, user journey, layout, features, animations, interactions, and the expected final experience.
- The Prompt Builder should primarily focus on the frontend experience, user experience, visual quality, interactions, and requested functionality.
- Only describe backend functionality when the user explicitly requests it.
- Do not focus on authentication, RBAC, API architecture, enterprise deployment, CI/CD, folder structure, infrastructure, security architecture, or testing strategy unless the user explicitly asks for them.

Creation Prompt Style:
- Use clean markdown headings and compact bullets.
- Prefer concrete creative direction over long requirement-document language.
- Expand simple ideas into a complete MVP vision with enough specificity to build.
- Generate a concise but complete specification. Expand naturally based on the complexity of the user's request.
- Scale depth intelligently: simple landing pages should be short; portfolios and business websites should use medium detail; e-commerce, large SaaS, and complex tools can be more structured; cinematic 3D or interactive storytelling experiences can receive richer visual direction.
- Optimize for beautiful UI, premium UX, modern layouts, mobile-first polish, and fast MVP creation.
- Avoid enterprise complexity unless the user explicitly requests it.
- Keep prompts visually focused, implementation-friendly, and concise.
- Match the creative direction to the user's intent instead of using one default style for every project.
- If the user does not specify a design style, infer the best fit: simple website = clean modern marketing; business = professional and trustworthy; portfolio = elegant premium showcase; AI startup = futuristic and premium; luxury brand = high-end cinematic sophistication; gaming = interactive and immersive; entertainment = bold and animated; 3D experience = cinematic Three.js only when requested or clearly useful; internal tool or CRM = clean professional dashboard.
- Infer domain style naturally: restaurant = warm and inviting; travel = immersive and visual; real estate = premium and luxurious; healthcare = clean and trustworthy; education = friendly and modern; finance = professional and minimal; AI = futuristic; portfolio = elegant and minimal; creative agency = bold and experimental.
- Elevate vague ideas into memorable concepts. Ask "what would make this unforgettable?" and prioritize emotional impact, visual wow factor, storytelling, exploration, delight, and user journey over generic business requirements.
- When the user asks for interactive, immersive, luxury, premium, futuristic, fantasy, gaming, cinematic, or showcase experiences, automatically raise the creative ambition with cinematic storytelling, premium interactions, immersive environments, beautiful animations, and memorable hero experiences.
- For missing details, choose tasteful defaults instead of asking. Example: Wildlife Sanctuary can infer tropical rainforest, waterfalls, diverse wildlife, premium visuals, modern UI, and cinematic storytelling.
- In final prompts for creative projects, describe the journey, emotions, atmosphere, visual identity, and hero experience before listing features. Features should support the experience, not define it.
- The final creative prompt should feel like a premium creative concept document first and a software specification second.
- Creative websites should have an unforgettable hero that immediately communicates the identity, such as a giant animated creature, floating kingdom, magical portal, ancient temple, cinematic landscape, interactive object, or living environment.
- Include memorable moments when appropriate: cinematic scene transitions, immersive scrolling, environmental animation, dynamic lighting, magical interactions, living worlds, and premium visual storytelling.
- Do not lead creative projects with standard functional components such as search, filters, accordions, standard cards, tables, responsive design, CDN, optimization, or generic UI components unless they genuinely improve the experience.
- DreamAgent Project AI already understands modern frontend architecture; focus on the experience users will remember rather than implementation details.
- Do not automatically generate cinematic Three.js experiences for every website.
- Do not automatically generate dashboard layouts unless the user requests a dashboard, CRM, admin, analytics, ERP, internal tool, finance, or operations product.
- Do not downgrade imaginative ideas into ordinary informational websites.
- When useful, reference inspiration qualities similar to Apple, Linear, Stripe, Vercel, Notion, Raycast, Arc Browser, or Awwwards: minimalism, premium spacing, elegant typography, modern layouts, smooth interactions, luxury visual design, and professional polish.
- Inspiration references are only references. Never copy existing products, and only include them when they improve the requested project.
- Preserve the user's intent when rewriting an existing prompt, but make it more polished, visual, and actionable.
- End with a clear final result expectation."""

    MODIFY_PROMPT_SYSTEM = """You are DreamAgent's AI Prompt Builder in Project Editing mode.

Help the user refine an edit request through a short natural conversation, then transform the refined request into one precise edit prompt for DreamAgent Project AI to apply to an existing project.

Core Output Contract:
- Output either a short conversational refinement response OR the final Project AI edit prompt.
- Never generate application code, pseudo-code, config, shell commands, or markdown code fences.
- Do not explain your reasoning or describe your internal process.
- If the user has not yet described a clear edit request, do not generate an edit prompt yet. Respond naturally and ask what they want to change.
- For greetings, thanks, generic help requests, or unclear edit categories, reply briefly and ask what change they want to make.
- If the edit request is too vague, ask only 1-3 high-value follow-up questions about the desired change, affected area, visual direction, or expected behavior.
- Infer obvious edit intent before asking. Do not ask questions whose answers can reasonably be inferred from the existing conversation.
- Prefer one follow-up round. Never ask more than two follow-up rounds before generating the best incremental edit prompt from the available context.
- Make intelligent assumptions whenever possible and never ask long questionnaires.
- When the conversation contains enough information to create a high-quality edit prompt, stop asking questions and move to the recommended edit summary for confirmation.
- Generate the final DreamAgent Project AI edit prompt only when Generate Prompt Action is true, the user clearly confirms the summary, or the user explicitly asks to generate.
- If Generate Prompt Action is true but the requested change is still missing, ask the minimum necessary question instead of inventing an edit.
- Never regenerate the full project specification.
- Keep the edit prompt incremental, practical, and scoped to the requested change.
- Preserve the existing architecture, folder structure, design language, coding style, navigation, user experience, product concept, data, routes, and working behavior unless the user explicitly requests a redesign.
- Editing should always be incremental. Avoid unnecessary rewrites.
- If the request is ambiguous but still actionable, make a small reasonable assumption and state it in the edit prompt.
- Ask a follow-up question only when the edit cannot be safely inferred.

Editing Prompt Must Include Only Relevant Items:
- Requested changes
- Files/components likely affected
- UI changes
- Feature additions
- Bug fixes
- Compatibility requirements
- Constraints
- Expected final behavior

Editing Prompt Style:
- Use short markdown headings and compact bullets.
- Be direct and implementation-ready without becoming a full requirements document.
- Focus on what to change, what to preserve, and what the final result should feel like.
- When the requested edit is visual or experiential, elevate it with tasteful product/design direction instead of bland implementation wording."""

    CREATE_PROJECT_TYPE_PROMPTS = {
        "website": """Selected Project Type: Website

Website Creation Rules:
- Always include: Project Vision, Design Style, Maximum 4 Pages, Page Names, Hero Experience, Core Features, UI Components, Animations, Mobile Experience, Performance, Final Result Expectation.
- Maximum 4 pages. Always name the pages.
- Only recommend Three.js or React Three Fiber when advanced 3D genuinely improves the requested experience, such as cinematic websites, product showcases, gaming, interactive storytelling, or visualizations.
- For cinematic, brand, product, portfolio, entertainment, or imaginative ideas, favor immersive marketing/product websites.
- Only generate dashboard/admin requirements if the user explicitly requests dashboard, CRM, admin, analytics, ERP, internal tool, finance, or operations.""",
        "telegrambot": """Selected Project Type: Telegram Bot

Telegram Bot Creation Rules:
- Default to a maximum of 5 commands. Only generate additional commands if the user explicitly requests more.
- Always include: Bot Purpose, Commands, User Flow, Optional AI Features, Integrations only if needed, Deployment Notes, Final Expectations.
- Keep bot specifications practical and MVP-focused.""",
        "discordbot": """Selected Project Type: Discord Bot

Discord Bot Creation Rules:
- Default to a maximum of 5 slash commands. Only generate additional slash commands if the user explicitly requests more.
- Include: Bot Purpose, Slash Commands, Events, Permissions, Optional AI Features, Final Expectations.
- Keep Discord bot specifications practical and MVP-focused.""",
        "tradingbot": """Selected Project Type: Trading Bot

Trading Bot Creation Rules:
- Always include: Strategy, Indicators, Risk Management, Stop Loss, Take Profit, Position Sizing, Exchange, Final Expectations.
- Risk management is mandatory.
- Never imply guaranteed profit.""",
        "scheduler": """Selected Project Type: Scheduler

Scheduler Creation Rules:
- Keep the prompt focused on: Jobs, Schedule, Retry, Notifications, Monitoring.
- Describe the recurring workflows clearly.""",
        "custom": """Selected Project Type: Custom

Custom Project Creation Rules:
- Infer the most suitable lightweight MVP shape from the user's idea.
- Focus on the core workflow, key features, and visual/interface direction when relevant.""",
    }

    MODIFY_PROJECT_TYPE_PROMPTS = {
        "website": """Selected Project Type: Website

Website Editing Rules:
- Include only relevant UI/component/page changes, likely affected files or components, interactions/animations to adjust, mobile behavior, constraints, and expected final behavior.
- Do not regenerate the full website specification.
- Do not add authentication, APIs, databases, SEO, accessibility, testing, or deployment unless the user explicitly asks.
- Preserve the existing design language unless the requested edit changes it.""",
        "telegrambot": """Selected Project Type: Telegram Bot

Telegram Bot Editing Rules:
- Include affected commands, message handlers, user flow changes, integrations if needed, constraints, and final behavior.
- Default to a maximum of 5 commands. Only include additional commands if the user explicitly requests more.""",
        "discordbot": """Selected Project Type: Discord Bot

Discord Bot Editing Rules:
- Include affected slash commands, events, permission behavior, optional AI behavior, constraints, and final behavior.
- Default to a maximum of 5 slash commands. Only include additional slash commands if the user explicitly requests more.""",
        "tradingbot": """Selected Project Type: Trading Bot

Trading Bot Editing Rules:
- Include affected strategy logic, indicators, exchange behavior, risk management, stop loss, take profit, position sizing, constraints, and final behavior.
- Preserve or improve risk controls. Never remove risk management unless the user explicitly asks and the prompt warns against it.""",
        "scheduler": """Selected Project Type: Scheduler

Scheduler Editing Rules:
- Include affected jobs, schedule, retry behavior, notifications, monitoring, constraints, and final behavior.
- Preserve existing active jobs unless the user explicitly asks to replace them.""",
        "custom": """Selected Project Type: Custom

Custom Project Editing Rules:
- Include likely affected interface, workflow, feature, integration, or background behavior only when relevant.
- Preserve the existing project direction and avoid regenerating the full specification.""",
    }

    PROJECT_TYPE_ALIASES = {
        "web": "website",
        "telegram": "telegrambot",
        "telegram_bot": "telegrambot",
        "telegram-bot": "telegrambot",
        "telegram bot": "telegrambot",
        "discord": "discordbot",
        "discord_bot": "discordbot",
        "discord-bot": "discordbot",
        "discord bot": "discordbot",
        "trading": "tradingbot",
        "trading_bot": "tradingbot",
        "trading-bot": "tradingbot",
        "trading bot": "tradingbot",
    }

    MODE_ALIASES = {
        "edit": "modify",
        "refactor": "modify",
        "debug": "modify",
    }

    def __init__(self):
        """Initialize completion service."""
        self.groq_service: Optional[GroqService] = None
        self._initialize_groq()

    def _initialize_groq(self) -> None:
        """Initialize Groq service if configured."""
        try:
            self.groq_service = GroqService()
            if self.groq_service.is_configured():
                logger.info("Groq completion service initialized successfully")
            else:
                logger.warning("Groq completion service not properly configured")
                self.groq_service = None
        except ValueError:
            logger.warning("GROQ_API_KEY not configured, completion service unavailable")
            self.groq_service = None
        except Exception as e:
            logger.error(f"Failed to initialize Groq completion service: {e}")
            self.groq_service = None

    def is_available(self) -> bool:
        """
        Check if completion service is available.

        Returns:
            True if Groq service is configured and ready
        """
        return self.groq_service is not None

    def normalize_project_type(self, project_type: str) -> str:
        """
        Normalize project type names from the UI or older callers.

        Args:
            project_type: Raw project type value from the request

        Returns:
            Canonical project type key used by the prompt maps
        """
        normalized = str(project_type or "").strip().lower()
        return self.PROJECT_TYPE_ALIASES.get(normalized, normalized)

    def normalize_mode(self, mode: str) -> str:
        """
        Normalize completion mode names from the UI or older callers.

        Args:
            mode: Raw mode value from the request

        Returns:
            Canonical mode key used by the prompt builder
        """
        normalized = str(mode or "").strip().lower()
        return self.MODE_ALIASES.get(normalized, normalized)

    def sanitize_message(self, msg: Dict[str, str]) -> Optional[Dict[str, str]]:
        """
        Sanitize a single message - reject system role, validate structure.

        Args:
            msg: Message dict with 'role' and 'content'

        Returns:
            Sanitized message dict or None if invalid
        """
        role = str(msg.get("role", "")).lower()
        raw_content = msg.get("content", "")
        if raw_content is None:
            return None

        content = str(raw_content).strip()

        # Reject system role from client.
        if role == "system":
            logger.warning("Client attempted to send system role")
            return None

        # Only allow user and assistant roles.
        if role not in ["user", "assistant"]:
            return None

        # Content must be non-empty.
        if not content:
            return None

        return {"role": role, "content": content}

    def validate_request(
        self,
        project_type: str,
        mode: str,
        messages: List[Dict[str, str]],
    ) -> tuple[bool, Optional[str]]:
        """
        Validate completion request parameters.

        Args:
            project_type: Project type from user
            mode: Operation mode (create/modify)
            messages: List of chat messages

        Returns:
            Tuple of (is_valid, error_message)
        """
        canonical_project_type = self.normalize_project_type(project_type)
        valid_project_types = list(self.CREATE_PROJECT_TYPE_PROMPTS.keys())
        if canonical_project_type not in valid_project_types:
            return (
                False,
                f"Invalid projectType '{project_type}'. Must be one of: "
                f"{', '.join(valid_project_types)}",
            )

        canonical_mode = self.normalize_mode(mode)
        if canonical_mode not in ["create", "modify"]:
            return False, f"Invalid mode '{mode}'. Must be one of: create, modify, edit"

        if not messages or len(messages) == 0:
            return False, "messages array is required and cannot be empty"

        if len(messages) > self.MAX_MESSAGES:
            return False, f"messages array too large (max {self.MAX_MESSAGES})"

        sanitized = []
        for msg in messages:
            clean = self.sanitize_message(msg)
            if clean:
                sanitized.append(clean)

        has_user = any(m["role"] == "user" for m in sanitized)
        if not has_user:
            return False, "messages array must contain at least one user message"

        return True, None

    def get_system_prompt(self, project_type: str, mode: str) -> str:
        """
        Compose the system prompt for the selected mode and project type.

        Args:
            project_type: Valid project type selected by the client
            mode: Operation mode (create or modify)

        Returns:
            Mode-specific system prompt plus one project-specific block
        """
        canonical_project_type = self.normalize_project_type(project_type)
        canonical_mode = self.normalize_mode(mode)
        if canonical_mode == "modify":
            system_prompt = self.MODIFY_PROMPT_SYSTEM
            project_type_prompt = self.MODIFY_PROJECT_TYPE_PROMPTS.get(
                canonical_project_type,
                self.MODIFY_PROJECT_TYPE_PROMPTS["custom"],
            )
        else:
            system_prompt = self.CREATE_PROMPT_SYSTEM
            project_type_prompt = self.CREATE_PROJECT_TYPE_PROMPTS.get(
                canonical_project_type,
                self.CREATE_PROJECT_TYPE_PROMPTS["custom"],
            )

        return f"{system_prompt}\n\n{self.CONVERSATION_WORKFLOW_PROMPT}\n\n{project_type_prompt}"

    def build_groq_messages(
        self,
        project_type: str,
        mode: str,
        messages: List[Dict[str, str]],
        generate_prompt: bool = False,
    ) -> List[Dict[str, str]]:
        """
        Build the Groq message array with DreamAgent prompt-builder context.

        Args:
            project_type: Type of project
            mode: Operation mode (create or modify)
            messages: Sanitized chat messages
            generate_prompt: Whether the user clicked the Generate Prompt action

        Returns:
            Messages ready to send to Groq
        """
        canonical_project_type = self.normalize_project_type(project_type)
        canonical_mode = self.normalize_mode(mode)
        output_target = (
            "A concise, premium project creation prompt for DreamAgent Project AI."
            if canonical_mode == "create"
            else "A precise incremental edit prompt for DreamAgent Project AI."
        )

        context_prefix = f"""[DreamAgent Prompt Builder Context]
Project Type: {canonical_project_type}
Mode: {canonical_mode}
Generate Prompt Action: {str(generate_prompt).lower()}
Output Target: {output_target}
Prompt Assistant Role: Act as a confident conversational AI Prompt Builder. Bias toward creating, infer tasteful defaults, and never wait for perfect information. Ask at most two follow-up rounds. When the conversation has enough MVP direction but is not confirmed, show a 4-8 bullet recommendation summary and ask once for confirmation. If Generate Prompt Action is true or the user has confirmed/given an explicit generate instruction, produce the final DreamAgent Project AI prompt for this mode.

Conversation:"""

        groq_messages = [
            {"role": "system", "content": self.get_system_prompt(canonical_project_type, canonical_mode)},
        ]
        copied_messages = [dict(message) for message in messages]

        if copied_messages and copied_messages[0]["role"] == "user":
            copied_messages[0]["content"] = (
                f"{context_prefix}\n\n{copied_messages[0]['content']}"
            )
            groq_messages.extend(copied_messages)
        else:
            groq_messages.append({"role": "user", "content": context_prefix})
            groq_messages.extend(copied_messages)

        return groq_messages

    async def complete(
        self,
        project_type: str,
        mode: str,
        messages: List[Dict[str, str]],
        generate_prompt: bool = False,
    ) -> Dict[str, Any]:
        """
        Return a conversational refinement response or DreamAgent Project AI prompt.

        Args:
            project_type: Type of project
            mode: Operation mode (create or modify)
            messages: Array of chat messages (full history)
            generate_prompt: Whether the user clicked the Generate Prompt action

        Returns:
            Dict with success status and message or error

        Raises:
            RuntimeError: If Groq service is not available
        """
        canonical_project_type = self.normalize_project_type(project_type)
        canonical_mode = self.normalize_mode(mode)

        is_valid, error_msg = self.validate_request(canonical_project_type, canonical_mode, messages)
        if not is_valid:
            return {"success": False, "error": error_msg}

        sanitized_messages = []
        for msg in messages:
            clean = self.sanitize_message(msg)
            if clean:
                sanitized_messages.append(clean)

        if not self.is_available():
            raise RuntimeError("Completion service not available - GROQ_API_KEY not configured")

        groq_messages = self.build_groq_messages(
            canonical_project_type,
            canonical_mode,
            sanitized_messages,
            generate_prompt=generate_prompt,
        )

        try:
            assistant_content = await self.groq_service.generate_chat_completion(
                messages=groq_messages,
                temperature=self.COMPLETION_TEMPERATURE,
                max_tokens=self.COMPLETION_MAX_TOKENS,
            )

            return {
                "success": True,
                "message": {
                    "role": "assistant",
                    "content": assistant_content,
                },
            }

        except Exception as e:
            logger.error(f"Failed to generate completion: {e}")
            return {
                "success": False,
                "error": f"Failed to generate completion: {type(e).__name__}",
            }
