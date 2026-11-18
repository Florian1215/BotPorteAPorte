####################################################### VARIABLE #######################################################
NAME		:=	canvassing
SRCS_D		:=	srcs
ENV_FILE	:=	$(SRCS_D)/.env
MODE		?=	prod
COMPOSE_F	?=	$(SRCS_D)/docker-compose.$(MODE).yml
SERVICE		?=	#Leave blank
TAIL		?=	100

######################################################## FLAGS #########################################################
FLAGS		=	-f $(COMPOSE_F)
COMPOSE		=	docker-compose
DSHELL		=	/bin/sh
MANAGE		=	$(COMPOSE) $(FLAGS) exec backend python manage.py

######################################################## RULES #########################################################
.DEFAULT_GOAL = all

.PHONY: all
all			:	$(NAME)

$(NAME)		:	$(ENV_FILE)
			$(COMPOSE) $(FLAGS) up --build $(SERVICE)

# Development mode: hot reload (Vite + Django runserver) on http://localhost:$(HTTP_PORT) (HTTP_PORT in srcs/.env)
.PHONY: dev
dev			:	$(ENV_FILE)
			$(MAKE) all MODE=dev

$(ENV_FILE)	:
			cp $(SRCS_D)/.env.example $(ENV_FILE)
			@echo "$(ENV_FILE) created from .env.example: change the secrets before going to production."

.PHONY: env
env			:	$(ENV_FILE)

CMDS		:=	up build down ps ls images top
.PHONY: $(CMDS)
$(CMDS)		:	$(ENV_FILE)
			$(COMPOSE) $(FLAGS) $@ $(SERVICE)

.PHONY: detach
detach		:	$(ENV_FILE)
			$(COMPOSE) $(FLAGS) up --build --$@ $(SERVICE)

.PHONY: logs
logs		:
			$(COMPOSE) $(FLAGS) $@ -f --tail=$(TAIL) $(SERVICE)

.PHONY: exec
exec		:
			$(COMPOSE) $(FLAGS) $@ $(SERVICE) $(DSHELL)

################################################### DJANGO HELPERS #####################################################
.PHONY: migrate makemigrations superuser shell seed import load-zensus load-social
migrate		:
			$(MANAGE) migrate
makemigrations:
			$(MANAGE) makemigrations
superuser	:
			$(MANAGE) createsuperuser
shell		:
			$(MANAGE) shell
seed		:
			$(MANAGE) seed_demo

import		:
			$(MANAGE) import_addresses $(FILE) $(if $(LIST),--list "$(LIST)",--organization $(ORG))

load-social:
			$(MANAGE) load_social_index

####################################################### CLEANING #######################################################
.PHONY: clean
clean		:
			$(COMPOSE) $(FLAGS) down --rmi local --remove-orphans

.PHONY: fclean
fclean		:	dusting
			$(COMPOSE) $(FLAGS) down -v --rmi all --remove-orphans

.PHONY: dusting
dusting		:
			find . -path "*/__pycache__/*" -delete
			find . -path "*/__pycache__" -delete

.PHONY: prune
prune		:
			docker system prune -af

.PHONY: re
re			:	clean all

.PHONY: vre
vre			:	fclean all
