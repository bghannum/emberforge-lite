class_name BriarKnightRoseVortexShieldController
extends Node2D

signal summon_visual_peak
signal summon_finished

@export var summon_sprite: AnimatedSprite2D

const SUMMON_ANIMATION := &"rose_vortex_shield"
const PEAK_FRAME := 10

var _peak_emitted := false


func _ready() -> void:
	assert(summon_sprite != null, "Assign the Briar Knight AnimatedSprite2D.")
	summon_sprite.frame_changed.connect(_on_frame_changed)
	summon_sprite.animation_finished.connect(_on_animation_finished)


func play_rose_vortex_shield() -> void:
	_peak_emitted = false
	summon_sprite.position = Vector2.ZERO
	summon_sprite.play(SUMMON_ANIMATION)


func _on_frame_changed() -> void:
	if summon_sprite.animation == SUMMON_ANIMATION and summon_sprite.frame == PEAK_FRAME and not _peak_emitted:
		_peak_emitted = true
		summon_visual_peak.emit()


func _on_animation_finished() -> void:
	if summon_sprite.animation != SUMMON_ANIMATION:
		return
	summon_sprite.play(&"idle")
	summon_finished.emit()
