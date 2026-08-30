class_name GravescribeDarkMistController
extends Node2D

signal cast_visual_peak
signal cast_finished
@export var cast_sprite: AnimatedSprite2D
const CAST_ANIMATION := &"dark_mist"
const PEAK_FRAME := 9
var _peak_emitted := false

func _ready() -> void:
	assert(cast_sprite != null, "Assign the Gravescribe AnimatedSprite2D.")
	cast_sprite.frame_changed.connect(_on_frame_changed)
	cast_sprite.animation_finished.connect(_on_animation_finished)

func play_dark_mist() -> void:
	_peak_emitted = false
	cast_sprite.position = Vector2.ZERO
	cast_sprite.play(CAST_ANIMATION)

func _on_frame_changed() -> void:
	if cast_sprite.animation == CAST_ANIMATION and cast_sprite.frame == PEAK_FRAME and not _peak_emitted:
		_peak_emitted = true
		cast_visual_peak.emit()

func _on_animation_finished() -> void:
	if cast_sprite.animation == CAST_ANIMATION:
		cast_sprite.play(&"idle")
		cast_finished.emit()
